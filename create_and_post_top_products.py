#!/usr/bin/env python3
"""
create_and_post_top_products.py — Génère un article "Top N" + visuels + publication Pinterest
==============================================================================================

PIPELINE :
  1. Sélection de niche (rotation scorée : days_since × weight × seasonal_boost × trend × jitter)
  2. Récupération produits diversifiés (llm_niches + niche_product_types filter)
  3. Génération contenu LLM (titre → intro → blurbs via Ollama Cloud)
  4. Génération visuels Pinterest 1000×1500 px (Hero / Spotlight / Checklist)
  5. Si production_workflow : upload R2 + publication Pinterest + upsert top_articles
     Sinon : sauvegarde locale dans output/top_pins/
  6. Mise à jour last_used dans product_taxonomy.json

Usage :
    python3 scripts/create_and_post_top_products.py                    # 1 article, config settings.py
    python3 scripts/create_and_post_top_products.py --count 3          # 3 articles
    python3 scripts/create_and_post_top_products.py --niche gaming_setup
    python3 scripts/create_and_post_top_products.py --month 2026-07
    python3 scripts/create_and_post_top_products.py --no-visuals       # Texte uniquement
    python3 scripts/create_and_post_top_products.py --dry-run
"""

import argparse
import hashlib
import io
import json
import random
import re
import sys
import time
import unicodedata
from datetime import datetime, date, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests
from tenacity import retry, wait_fixed, stop_after_attempt, retry_if_exception_type

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    _PIL = True
except ImportError:
    _PIL = False

from settings import (
    ROOT, SUPABASE_URL, SUPABASE_KEY,
    OLLAMA_CLOUD_API_KEY, OLLAMA_CLOUD_HOST, OLLAMA_CLOUD_MODEL, OLLAMA_CLOUD_PINS_MODEL,
    HF_API_TOKEN, PINTEREST_ACCESS_TOKEN, PINTEREST_API_BASE, PINTEREST_BOARD_ID,
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_PUBLIC_URL,
    SITE_URL, TAXONOMY_PATH, FONTS_DIR, OUTPUT_DIR, LOCAL_PINTEREST_DIR,
    production_workflow, nb_products_per_article, nb_pins_per_article,
    sb_headers, check_supabase, get_board_for_niche,
)

# ── Config placeholder images (source unique de vérité) ─────────────────────
_PLACEHOLDER_CFG_PATH = ROOT / "src" / "config" / "placeholder_images.json"

def _load_placeholder_cfg() -> dict[str, list[str]]:
    """Charge le JSON de référence des images placeholder par marchand."""
    try:
        raw = json.loads(_PLACEHOLDER_CFG_PATH.read_text(encoding="utf-8"))
        return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, list)}
    except Exception:
        return {}

_PLACEHOLDER_CFG: dict[str, list[str]] = _load_placeholder_cfg()


def _resolve_productserve_url(url: str) -> str:
    """Décode un proxy productserve.com?url=ssl%3A... → URL CDN directe."""
    if not url:
        return url
    if "productserve.com" in url and "url=" in url:
        try:
            qs = parse_qs(urlparse(url).query)
            raw = qs.get("url", [""])[0]
            if raw:
                decoded = unquote(raw)
                if decoded.startswith("ssl://"):
                    return "https://" + decoded[6:]
                if decoded.startswith("ssl:"):
                    return "https://" + decoded[4:]
                return decoded
        except Exception:
            pass
    return url


# ── Pixel hash pour la détection des placeholders visuels (CDNs à URLs multiples) ─
_PIXEL_HASH_CACHE: dict[str, str | None] = {}   # URL → hash (None = échec)
_REF_PIXEL_HASHES: dict[str, list[str]] | None = None  # lazy-loaded


def _pixel_hash(data: bytes) -> str:
    """Hash MD5 d'une normalisation 64×64 RGBA — même algo que check_affiliate_links.py."""
    img = Image.open(io.BytesIO(data)).convert("RGBA").resize((64, 64), Image.LANCZOS)
    return hashlib.md5(img.tobytes()).hexdigest()


def _get_pixel_hash_for_url(url: str) -> str | None:
    """Télécharge et hash une image (résultat mis en cache par URL)."""
    if url in _PIXEL_HASH_CACHE:
        return _PIXEL_HASH_CACHE[url]
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        h = _pixel_hash(r.content)
        _PIXEL_HASH_CACHE[url] = h
        return h
    except Exception:
        _PIXEL_HASH_CACHE[url] = None
        return None


def _get_ref_pixel_hashes() -> dict[str, list[str]]:
    """Charge (paresseusement) les hashes pixels de référence depuis placeholder_images.json."""
    global _REF_PIXEL_HASHES
    if _REF_PIXEL_HASHES is not None:
        return _REF_PIXEL_HASHES
    if not _PIL:
        _REF_PIXEL_HASHES = {}
        return _REF_PIXEL_HASHES
    result: dict[str, list[str]] = {}
    for merchant, urls in _PLACEHOLDER_CFG.items():
        hashes = [h for url in urls for h in [_get_pixel_hash_for_url(url)] if h]
        if hashes:
            result[merchant] = hashes
    _REF_PIXEL_HASHES = result
    return _REF_PIXEL_HASHES


def _is_valid_product_image(image_url: str | None, merchant_key: str) -> bool:
    """
    Retourne True seulement si l'image est réelle (non-placeholder, non-vide).
    Détection en deux passes :
      1. Comparaison d'URL (sans réseau) — cas simples
      2. Comparaison pixel 64×64 RGBA MD5 (download) — CDNs à URLs variables (ex: Rue du Commerce)
    """
    if not image_url:
        return False
    image_url = image_url.strip().replace('%22', '').rstrip('"')
    if not image_url:
        return False
    known_placeholders = _PLACEHOLDER_CFG.get(merchant_key, [])
    if not known_placeholders:
        return True  # marchand sans config → on accepte
    resolved = _resolve_productserve_url(image_url)
    # Passe 1 : URL
    if image_url in known_placeholders or resolved in known_placeholders:
        return False
    # Passe 2 : pixel hash (couvre les CDNs qui servent le même placeholder depuis plusieurs URLs)
    if _PIL:
        ref_hashes = _get_ref_pixel_hashes().get(merchant_key, [])
        if ref_hashes:
            img_hash = _get_pixel_hash_for_url(resolved)
            if img_hash and img_hash in ref_hashes:
                return False
    return True


# ── Constantes ────────────────────────────────────────────────────────────────
PIN_W, PIN_H = 1000, 1500

MONTH_FR = {
    "01": "janvier", "02": "février",   "03": "mars",    "04": "avril",
    "05": "mai",     "06": "juin",      "07": "juillet", "08": "août",
    "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre",
}

_NICHE_LABEL_EN: dict[str, str] = {
    "bedroom_essentials": "your bedroom",
    "living_room_storage": "your living room",
    "kitchen_organization": "your kitchen",
    "cable_management": "cable management",
    "bathroom_storage": "your bathroom",
    "small_space_solutions": "small space living",
    "entryway_decor": "your entryway",
    "outdoor_living": "outdoor living",
    "cozy_lighting": "cozy lighting",
    "closet_organization": "your wardrobe",
    "home_office_setup": "your home office",
    "kids_room": "kids room",
    "eco_home": "eco-friendly home",
    "smart_home": "your smart home",
    "gaming_setup": "your gaming setup",
    "audio_hi_fi": "your hi-fi experience",
    "mobile_nomade": "nomad & travel gear",
}

_PRODUCT_SELECT = (
    "id,name,brand,image_url,category_slug,"
    "affiliate_url,price,currency,merchant_key,description,llm_product_type"
)
_ORDER_QUALITY = "&order=price.asc.nullslast"  # rating non fiable en DB, on trie par prix croissant

TREND_REGIONS = ["FR", "US", "GB", "DE"]
TREND_TYPES = ["growing", "monthly", "yearly"]


# ── Taxonomie ─────────────────────────────────────────────────────────────────

def _load_taxonomy() -> dict:
    if not TAXONOMY_PATH.exists():
        print(f"❌  {TAXONOMY_PATH} introuvable")
        sys.exit(1)
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def _save_taxonomy(data: dict) -> None:
    TAXONOMY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ── Supabase ──────────────────────────────────────────────────────────────────

def sb_get(path: str, params: str = "") -> list:
    url = f"{SUPABASE_URL}/rest/v1/{path}{'?' + params if params else ''}"
    r = requests.get(url, headers=sb_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def sb_upsert(table: str, row: dict, on_conflict: str | None = None) -> bool:
    h = sb_headers({"Prefer": "resolution=merge-duplicates,return=minimal"})
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if on_conflict:
        url += f"?on_conflict={on_conflict}"
    r = requests.post(url, headers=h, json=row, timeout=30)
    if r.status_code not in (200, 201, 204):
        print(f"  ⚠️  UPSERT {table}: HTTP {r.status_code} — {r.text[:200]}")
        return False
    return True


def sb_patch(table: str, filter_param: str, patch: dict) -> bool:
    """PATCH (partial update) on rows matching filter_param (e.g. 'slug=eq.my-slug')."""
    h = sb_headers({"Prefer": "return=minimal"})
    r = requests.patch(f"{SUPABASE_URL}/rest/v1/{table}?{filter_param}", headers=h, json=patch, timeout=30)
    if r.status_code not in (200, 204):
        print(f"  ⚠️  PATCH {table}: HTTP {r.status_code} — {r.text[:200]}")
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
# NICHE SELECTION
# ══════════════════════════════════════════════════════════════════════════════

def _niche_product_counts(taxonomy: dict) -> dict[str, int]:
    """Pré-comptage des produits disponibles par niche (avec filtre product_type)."""
    rows = sb_get("products",
                  "select=llm_niches,llm_product_type&active=not.is.false&llm_niches=not.is.null")
    niche_product_types = taxonomy.get("niche_product_types", {})
    counts: dict[str, int] = {}
    for row in rows:
        pt = row.get("llm_product_type") or ""
        for n in (row.get("llm_niches") or []):
            allowed = set(niche_product_types.get(n, []))
            if allowed and pt not in allowed:
                continue
            counts[n] = counts.get(n, 0) + 1
    viable = {n: c for n, c in sorted(counts.items(), key=lambda x: -x[1]) if c >= 3}
    print(f"  📊 {len(viable)} niches viables (≥3 produits) sur {len(counts)} classifiées")
    if viable:
        top5 = list(viable.items())[:5]
        print(f"     Top 5 : {dict(top5)}")
    return counts


def _days_since(niche: str, last_used: dict) -> float:
    val = last_used.get(niche)
    if not val or val == "null":
        return 999.0
    try:
        return max(0.0, (date.today() - datetime.fromisoformat(str(val)).date()).days)
    except (ValueError, TypeError):
        return 999.0


def _current_boosted(taxonomy: dict) -> list:
    month = datetime.now().month
    for rng, niches in taxonomy.get("seasonal_boost", {}).items():
        parts = rng.split("-")
        if len(parts) == 2:
            s, e = int(parts[0]), int(parts[1])
            if (s <= e and s <= month <= e) or (s > e and (month >= s or month <= e)):
                return niches
    return []


def pick_niche(taxonomy: dict, trends: dict,
               forced: Optional[str] = None, exclude: Optional[set] = None,
               niche_counts: Optional[dict] = None, min_products: int = 3) -> str:
    """Score = days_since × weight × seasonal_boost × count_bonus × jitter
    Niches sans assez de produits en DB sont automatiquement exclues."""
    if forced:
        return forced

    niches = [n for n in taxonomy.get("niches", {}).keys() if n not in (exclude or set())]

    # Filtrer les niches sans assez de produits
    if niche_counts is not None:
        viable = [n for n in niches if niche_counts.get(n, 0) >= min_products]
        if viable:
            excluded = len(niches) - len(viable)
            if excluded:
                print(f"  🔎 {excluded} niches exclues (< {min_products} produits en DB)")
            niches = viable
        else:
            print(f"  ⚠️  Aucune niche n'a >= {min_products} produits — sélection sans filtre")

    last_used = taxonomy.get("last_used", {})
    boosted = _current_boosted(taxonomy)

    scores = {}
    for n in niches:
        days = _days_since(n, last_used)
        weight = taxonomy.get("weights", {}).get(n, 1.0)
        boost = 2.0 if n in boosted else 1.0
        # Bonus proportionnel au nombre de produits disponibles
        count_mult = 1.0
        if niche_counts is not None:
            cnt = niche_counts.get(n, 0)
            count_mult = 1.0 + min(2.0, cnt / 20.0)
        jitter = random.uniform(0.8, 1.2)
        scores[n] = days * weight * boost * count_mult * jitter

    if not scores:
        print("  ⚠️  Plus aucune niche disponible")
        return None

    chosen = max(scores, key=scores.__getitem__)
    top5 = sorted(scores.items(), key=lambda x: -x[1])[:5]
    print(f"  📅 Mois {datetime.now().month}  |  Boostées: {_current_boosted(taxonomy)[:4]}")
    print(f"  🎯 Niche choisie : {chosen}", end="")
    if niche_counts:
        print(f"  ({niche_counts.get(chosen, 0)} produits)")
    else:
        print()
    print(f"     Top 5 scores : { {k: round(v) for k, v in top5} }")
    return chosen


# ══════════════════════════════════════════════════════════════════════════════
# PINTEREST TRENDS
# ══════════════════════════════════════════════════════════════════════════════

def fetch_pinterest_trends() -> dict:
    if not PINTEREST_ACCESS_TOKEN:
        print("  ℹ️  PINTEREST_ACCESS_TOKEN absent — tendances ignorées")
        return {}

    headers = {"Authorization": f"Bearer {PINTEREST_ACCESS_TOKEN}", "Accept": "application/json"}
    raw: dict = {}

    for region in TREND_REGIONS:
        for tt in TREND_TYPES:
            url = f"{PINTEREST_API_BASE}/trends/keywords/{region}/top/{tt}"
            try:
                r = requests.get(url, headers=headers,
                                 params={"limit": 50, "include_demographics": "true"}, timeout=15)
                if r.status_code != 200:
                    continue
                for item in r.json().get("trends", []):
                    kw = item.get("keyword", "").strip().lower()
                    if not kw:
                        continue
                    def _safe(v):
                        if v is None: return None
                        f = float(v)
                        return None if f >= 10001 else f
                    entry = {
                        "wow": _safe(item.get("pct_growth_wow")),
                        "mom": _safe(item.get("pct_growth_mom")),
                        "yoy": _safe(item.get("pct_growth_yoy")),
                        "regions": [region],
                    }
                    if kw not in raw:
                        raw[kw] = entry
                    else:
                        if region not in raw[kw]["regions"]:
                            raw[kw]["regions"].append(region)
                        for metric in ("wow", "mom", "yoy"):
                            if raw[kw][metric] is None:
                                raw[kw][metric] = entry[metric]
            except Exception as e:
                print(f"  ⚠️  Trends {region}/{tt}: {e}")

    result = {}
    for kw, d in raw.items():
        w = d["wow"] or 0
        m = d["mom"] or 0
        if   w >= 30 and m < 120: phase = "emerging"
        elif w >= 15 and m >= 80: phase = "accelerating"
        elif w >= 5  and m >= 60: phase = "peak"
        elif w < 0:               phase = "declining"
        else:                     phase = "stable"
        result[kw] = {**d, "phase": phase, "score": w + m * 0.3,
                      "region_count": len(set(d["regions"]))}

    surfable = sum(1 for d in result.values() if d["phase"] in ("emerging", "accelerating", "peak"))
    print(f"  📈 {len(result)} tendances Pinterest — {surfable} en phase surfable")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCT FETCHING
# ══════════════════════════════════════════════════════════════════════════════

# Durée de cooldown par défaut : un produit utilisé dans les N derniers jours est pénalisé.
PRODUCT_COOLDOWN_DAYS = 21


def _fetch_recently_used_ids(days: int = PRODUCT_COOLDOWN_DAYS) -> set:
    """Retourne l'ensemble des IDs produits utilisés dans des articles récents (production only)."""
    try:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = sb_get(
            "top_articles",
            f"created_at=gte.{cutoff}&select=ids_products_used",
        )
        recent: set = set()
        for row in rows:
            ids = row.get("ids_products_used") or []
            if isinstance(ids, list):
                recent.update(ids)
        if recent:
            print(f"  🔒 Cooldown : {len(recent)} produit(s) utilisé(s) ces {days} derniers jours → déprioritisés")
        return recent
    except Exception as e:
        print(f"  ⚠️  Cooldown fetch: {e}")
        return set()


def _pick_diverse(rows: list, count: int,
                  seen_ids: set | None = None, seen_types: set | None = None) -> list:
    if seen_ids   is None: seen_ids   = set()
    if seen_types is None: seen_types = set()
    products = []
    for row in rows:
        if len(products) >= count:
            break
        if row["id"] in seen_ids:
            continue
        if not (row.get("affiliate_url") or row.get("price")):
            continue
        pt = row.get("llm_product_type") or ""
        if pt and pt in seen_types:
            continue
        seen_ids.add(row["id"])
        if pt:
            seen_types.add(pt)
        products.append(row)
    return products


def fetch_diverse_products(niche: str, count: int, taxonomy: dict) -> list:
    try:
        rows = sb_get("products",
                       f"llm_niches=cs.{{{niche}}}{_ORDER_QUALITY}"
                       f"&limit={count * 12}&active=not.is.false&select={_PRODUCT_SELECT}")

        # ── Cooldown : déprioritiser les produits récemment utilisés (production only) ──
        if production_workflow and rows:
            recent_ids = _fetch_recently_used_ids()
            if recent_ids:
                fresh  = [r for r in rows if r["id"] not in recent_ids]
                stale  = [r for r in rows if r["id"] in recent_ids]
                rows = fresh + stale  # fresh d'abord, récents en dernier recours

        products = _pick_diverse(rows, count) if rows else []
    except Exception as e:
        print(f"  ⚠️  llm_niches query: {e}")
        products = []

    if not products:
        print(f"  ⚠️  Aucun produit classifié pour '{niche}'")

    print(f"\n  📦 {len(products)} produits pour '{niche}' :")
    for i, p in enumerate(products[:count], 1):
        cat = p.get("llm_product_type") or p.get("category_slug") or ""
        name = (p.get("name") or "")[:55]
        print(f"     {i}. [{cat}] {p.get('brand','?')} — {name} — {p.get('price','?')} €")
    return products[:count]


# ══════════════════════════════════════════════════════════════════════════════
# LLM — Ollama Cloud
# ══════════════════════════════════════════════════════════════════════════════

def _call_llm(prompt: str, max_tokens: int = 400, model: str = None) -> Optional[str]:
    if not OLLAMA_CLOUD_API_KEY:
        return None
    _model = model or OLLAMA_CLOUD_MODEL
    for attempt in range(3):
        try:
            r = requests.post(
                f"{OLLAMA_CLOUD_HOST}/api/chat",
                headers={"Authorization": f"Bearer {OLLAMA_CLOUD_API_KEY}",
                         "Content-Type": "application/json"},
                json={"model": _model,
                      "messages": [{"role": "user", "content": prompt}],
                      "stream": False,
                      "think": False,
                      "options": {"temperature": 0.55, "num_predict": max_tokens}},
                timeout=90,
            )
            if r.status_code == 429:
                wait = 12 * (attempt + 1)
                print(f"  ⏳ Rate limit LLM — attente {wait}s…")
                time.sleep(wait)
                continue
            r.raise_for_status()
            text = r.json()["message"]["content"].strip()
            text = re.sub(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+", "", text).strip()
            return text
        except Exception as e:
            if attempt < 2:
                print(f"  ⏳ LLM tentative {attempt+1}/3: {e} — retry 8s…")
                time.sleep(8)
            else:
                print(f"  ⚠️  Ollama Cloud échec: {e}")
    return None


def generate_pin_content(title: str, niche_label: str, n: int,
                         products: list, month_fr: str, year: str) -> dict:
    """Génère le contenu Pinterest en FR et EN via un seul appel LLM (JSON structuré)."""
    product_list = "\n".join(
        f"{i+1}. {p.get('name','?')} ({p.get('brand','?')}, {p.get('price','?')} €)"
        for i, p in enumerate(products[:n])
    )

    prompt = f"""Tu génères du contenu Pinterest en FRANÇAIS et en ANGLAIS.

Thème : {niche_label} — {n} produits — {month_fr} {year}
Produits : {product_list}

Retourne UNIQUEMENT un objet JSON valide (aucun texte avant ou après) :
{{
  "fr": {{
    "pin_title": "Titre pin français (50-100 car, émotionnel/FOMO, NE PAS commencer par Top)",
    "overlay_hero": "Texte overlay FR (5-10 mots, percutant)",
    "description": "Description Pinterest FR : accroche + 2-3 phrases bénéfices + CTA + 6-8 hashtags FR"
  }},
  "en": {{
    "pin_title": "Pin title in English (50-100 chars, emotional/FOMO, DO NOT start with Top)",
    "overlay_hero": "Overlay text EN (5-10 words, punchy)",
    "description": "Pinterest EN: hook + 2-3 benefit sentences + CTA + 6-8 English hashtags"
  }}
}}"""

    raw = _call_llm(prompt, 800, model=OLLAMA_CLOUD_PINS_MODEL) or ""
    fr_data: dict = {}
    en_data: dict = {}
    try:
        cleaned = re.sub(r"```json\s*|\s*```", "", raw).strip()
        j_start = cleaned.find("{")
        j_end   = cleaned.rfind("}") + 1
        if j_start != -1 and j_end > j_start:
            cleaned = cleaned[j_start:j_end]
        d = json.loads(cleaned)
        fr_data = d.get("fr", {})
        en_data = d.get("en", {})
    except Exception:
        pass

    def _ct(t, fb): return (t or "").strip().strip('"').strip("'").split("\n")[0][:100] or fb
    def _co(t, fb):
        t = (t or "").strip().strip('"').strip("'").split("\n")[0]
        return t if t else fb
    def _cd(t, fb): t = (t or "").strip(); return t[:500] if len(t) >= 60 else fb

    fb_overlay = f"Sélection {niche_label} {month_fr}"
    fb_overlay_en = f"Top picks for {niche_label}"

    pin_title_fr = _ct(fr_data.get("pin_title"), title)
    overlay_fr   = _co(fr_data.get("overlay_hero"), fb_overlay)
    desc_fr      = _cd(fr_data.get("description"), f"Nos {n} coups de cœur {niche_label} de {month_fr} {year}.")

    pin_title_en = _ct(en_data.get("pin_title"), title)
    overlay_en   = _co(en_data.get("overlay_hero"), fb_overlay_en)
    desc_en      = _cd(en_data.get("description"), f"Our top {n} picks for {niche_label} in {month_fr} {year}.")

    return {
        "pin_title": pin_title_fr,          # backward-compat alias
        "description": desc_fr,             # backward-compat alias
        "overlay_texts": [overlay_fr, overlay_en, f"Top {n} {niche_label}"],
        "fr": {"pin_title": pin_title_fr, "overlay_hero": overlay_fr, "description": desc_fr},
        "en": {"pin_title": pin_title_en, "overlay_hero": overlay_en, "description": desc_en},
    }


def generate_content(niche: str, niche_label: str, month_fr: str, year: str,
                     products: list, taxonomy: dict) -> dict:
    """Génère titre, intro, blurbs ET un article riche (HTML) avec liens affiliés intégrés, FR et EN."""
    n = len(products)

    product_list = "\n".join(
        f"{i+1}. {p.get('name','?')} ({p.get('brand','?')}, {p.get('price','?')} €)"
        for i, p in enumerate(products)
    )

    # Pré-calcul : mapping produit → lien affilié pour injection dans le prompt
    product_links = []
    for i, p in enumerate(products):
        aff_url = p.get("affiliate_url") or p.get("url") or "#"
        product_links.append({
            "name": p.get("name", "?"),
            "brand": p.get("brand", ""),
            "price": p.get("price", "?"),
            "url": aff_url,
            "product_type": p.get("llm_product_type", ""),
            "description": (p.get("description") or "").strip(),
            "merchant": p.get("merchant_key", ""),
        })

    products_with_links = "\n".join(
        f'{i+1}. {pl["name"]} ({pl["brand"]}, {pl["price"]} €) — LIEN: {pl["url"]}'
        for i, pl in enumerate(product_links)
    )

    # ── 1. Titre + Intro bilingues en un seul appel ─────────────────────────
    title_intro_raw = _call_llm(
        f"""Génère le titre et l'introduction d'un article de blog d'affiliation pour le thème "{niche_label}" ({month_fr} {year}).

{n} produits : {product_list}

IMPORTANT: Le titre doit être accrocheur et attrayant, PAS un simple "Top {n} accessoires pour..." mais quelque chose de plus créatif et engageant.
Exemples de bons titres : "Les pépites tech qui transforment votre quotidien", "Notre sélection coup de cœur pour un intérieur connecté", etc.

Retourne EXACTEMENT ce format (rien d'autre) :
FR_TITLE: [titre français percutant et accrocheur, 45-70 caractères]
EN_TITLE: [english title, 45-70 chars, catchy and engaging]
===FR_INTRO===
[Introduction française, 50-70 mots, ton naturel et direct, accrocheur]
===EN_INTRO===
[English introduction, 50-70 words, warm direct tone, engaging]""",
        800,
    ) or ""

    # Parser le résultat
    def _extract_line(text: str, key: str) -> str:
        m = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
        return m.group(1).strip().strip('"').strip("'") if m else ""

    def _extract_section(text: str, marker: str, next_marker: str = None) -> str:
        start_idx = text.find(marker)
        if start_idx == -1:
            return ""
        start = start_idx + len(marker)
        end = text.find(next_marker, start) if next_marker else len(text)
        return text[start:end].strip()

    title_fr = _extract_line(title_intro_raw, "FR_TITLE")
    title_en = _extract_line(title_intro_raw, "EN_TITLE")
    intro_fr = _extract_section(title_intro_raw, "===FR_INTRO===", "===EN_INTRO===")
    intro_en = _extract_section(title_intro_raw, "===EN_INTRO===")

    # Fallbacks
    if not title_fr or len(title_fr) < 20:
        title_fr = f"Notre sélection coup de cœur pour {niche_label} — {month_fr} {year}"
    if not title_en or len(title_en) < 20:
        title_en = f"Our top picks for {niche_label} — {month_fr} {year}"
    if not intro_fr or len(intro_fr) < 50:
        intro_fr = (f"Découvrez notre sélection de {n} produits incontournables pour "
                    f"{niche_label} en {month_fr} {year}.")
    if not intro_en or len(intro_en) < 50:
        intro_en = (f"Discover our selection of {n} must-have products for "
                    f"{niche_label} in {month_fr} {year}.")
    time.sleep(2)

    # ── 2. Blurbs produits (FR) ─────────────────────────────────────────────
    blurbs_raw = _call_llm(
        f"Génère une description courte (1 phrase, style factuel, avantage concret principal) "
        f"pour chacun de ces {n} produits destinés à {niche_label}.\n"
        f"Réponds UNIQUEMENT en français avec {n} lignes numérotées, sans texte avant ni après.\n"
        + "\n".join(f"{i+1}. ..." for i in range(n))
        + f"\n\nProduits :\n{product_list}",
        600
    )
    fallback_blurbs = [
        f"{p.get('brand','')} {p.get('name','')} — idéal pour {niche_label}.".strip()
        for p in products
    ]
    if blurbs_raw:
        parsed = re.findall(r"^\d+\.\s*(.+)", blurbs_raw, re.MULTILINE)
        blurbs_fr = (
            [re.sub(r"\s+", " ", b).strip() for b in parsed[:n]]
            if len(parsed) >= n
            else parsed + fallback_blurbs[len(parsed):]
        )
    else:
        blurbs_fr = fallback_blurbs

    time.sleep(2)

    # ── 3. Article bilingue (un seul appel LLM, Markdown → HTML) ────────────
    article_html_fr, article_html_en = _generate_article_body_bilingual(
        title_fr, title_en, products, niche_label, month_fr, year
    )

    return {
        "title": title_fr,
        "title_en": title_en,
        "intro": intro_fr,
        "intro_en": intro_en,
        "blurbs": blurbs_fr,
        "body_html_fr": article_html_fr,
        "body_html_en": article_html_en,
    }


def _slugify_product(text: str) -> str:
    """Slug ASCII simple pour les balises PRODUCT_IMAGE."""
    text = text.lower()
    for src, dst in [("éèêë", "e"), ("àâä", "a"), ("ùûü", "u"), ("ôö", "o"), ("îï", "i"), ("ç", "c")]:
        for c in src:
            text = text.replace(c, dst)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:45]


def _markdown_body_to_html(text: str, products: list, lang: str = "fr") -> str:
    """Convertit le corps généré par le LLM → HTML propre.
    Layout quinconce :
      - Produit avec vraie image → bloc flex [image | texte] (alternance gauche/droite)
      - Produit sans image ou placeholder → paragraphe pleine largeur
    """
    if not text:
        return ""

    def _esc(s: str) -> str:
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

    cta_label = "Je fonce !" if lang == "fr" else "I'm in!"

    # ── Construire product_map : slug → info (uniquement si image valide) ──
    product_map: dict[str, dict] = {}
    # Map slug → produit pour les blocs sans image aussi (pour le texte)
    product_text_map: dict[str, dict] = {}
    for p in products:
        slug = _slugify_product(f"{p.get('brand', '')}-{(p.get('name', '') or '')[:35]}")
        img_url = (p.get("image_url") or "").strip().replace('%22', '').rstrip('"')
        img_url = _resolve_productserve_url(img_url)  # proxy → URL CDN directe
        merchant_key = p.get("merchant_key") or ""
        name = (p.get("name") or "").strip()
        aff_url = p.get("affiliate_url") or p.get("url") or "#"
        product_text_map[slug] = {"name": name, "url": aff_url}
        if _is_valid_product_image(img_url, merchant_key):
            product_map[slug] = {"img": img_url, "name": name, "url": aff_url}

    # ── Convertir Markdown inline → HTML ──
    def _md_inline(s: str) -> str:
        def _link_sub(m: re.Match) -> str:
            link_text = m.group(1)
            url = m.group(2).replace('&', '&amp;')
            return f'<a href="{url}" target="_blank" rel="noopener noreferrer nofollow sponsored">{link_text}</a>'
        s = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", _link_sub, s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*([^*]+)\*",   r"<em>\1</em>", s)
        return s

    # ── Isoler les balises image sur leur propre paragraphe ──
    text = re.sub(
        r"\{\{PRODUCT_IMAGE:([^}]+)\}\}",
        lambda m: "\n\n{{PRODUCT_IMAGE:" + m.group(1) + "}}\n\n",
        text,
    )

    # ── Segmenter en blocs ("img", slug) | ("text", contenu) ──
    segments: list[tuple[str, str]] = []
    for para in re.split(r"\n{2,}", text.strip()):
        para = para.strip()
        if not para:
            continue
        m = re.match(r"^\{\{PRODUCT_IMAGE:([^}]+)\}\}$", para)
        if m:
            segments.append(("img", m.group(1)))
        else:
            # Nettoyer les balises image résiduelles dans les blocs texte
            para = re.sub(r"\{\{PRODUCT_IMAGE:[^}]+\}\}", "", para).strip()
            if para:
                segments.append(("text", para))

    # ── Construire le HTML avec couplage image + texte suivant ──
    html_parts: list[str] = []
    img_count = 0  # compte seulement les blocs avec vraie image (pour l'alternance)
    i = 0
    while i < len(segments):
        kind, val = segments[i]

        if kind == "img":
            slug = val.strip()
            prod = product_map.get(slug)          # None si pas de vraie image
            txt_info = product_text_map.get(slug) # toujours disponible

            # Consommer le prochain bloc texte (corps du paragraphe produit)
            next_text = ""
            if i + 1 < len(segments) and segments[i + 1][0] == "text":
                next_text = segments[i + 1][1]
                i += 1

            if prod and next_text:
                # ── Bloc quinconce : [image | texte] ou [texte | image] ──
                side = "left" if img_count % 2 == 0 else "right"
                img_count += 1
                name_esc = _esc(prod["name"])
                cta_url = prod["url"].replace('&', '&amp;')
                html_parts.append(
                    f'<div class="product-block product-block-{side}">'
                    f'<div class="product-block-media">'
                    f'<img src="{prod["img"]}" alt="{name_esc}" class="product-block-img" loading="lazy"'
                    f' onerror="this.style.display=\'none\'">'
                    f'</div>'
                    f'<div class="product-block-text">'
                    f'<p>{_md_inline(next_text.replace(chr(10), "<br>"))}</p>'
                    f'<a href="{cta_url}" class="product-block-cta"'
                    f' target="_blank" rel="noopener noreferrer nofollow sponsored">{cta_label}</a>'
                    f'</div>'
                    f'</div>'
                )
            elif next_text:
                # ── Pas d'image valide → paragraphe pleine largeur + CTA ──
                noimg_url = (txt_info or {}).get("url", "#").replace('&', '&amp;')
                noimg_cta = (
                    f'<a href="{noimg_url}" class="product-block-cta"'
                    f' target="_blank" rel="noopener noreferrer nofollow sponsored">{cta_label}</a>'
                ) if noimg_url != "#" else ""
                html_parts.append(
                    f'<div class="product-block product-block-noimg">'
                    f'<p>{_md_inline(next_text.replace(chr(10), "<br>"))}</p>'
                    f'{noimg_cta}'
                    f'</div>'
                )
            # Si aucun texte associé → on ignore le tag image

        else:  # kind == "text" non précédé d'une image → paragraphe libre
            para = val
            if re.match(r"^<(div|p|h[1-6]|ul|ol|li|blockquote)\b", para):
                html_parts.append(para)
            else:
                html_parts.append(f"<p>{_md_inline(para.replace(chr(10), '<br>'))}</p>")

        i += 1

    return "\n".join(html_parts)


def _generate_article_body_bilingual(
    title_fr: str, title_en: str,
    products: list, niche_label: str, month_fr: str, year: str
) -> tuple:
    """Génère le corps de l'article bilingue (FR + EN) en un seul appel LLM.
    Utilise le format Markdown avec balises {{PRODUCT_IMAGE:slug}} et liens [name](url).
    Retourne (body_html_fr, body_html_en) après conversion Markdown → HTML.
    """
    prod_blocks = []
    for i, p in enumerate(products, 1):
        name        = (p.get("name")            or "?").strip()
        brand       = (p.get("brand")           or "?").strip()
        price       = p.get("price")            or "?"
        url         = p.get("affiliate_url")    or p.get("url") or ""
        product_type = (p.get("llm_product_type") or "").strip()
        description  = (p.get("description")    or "").strip()
        slug  = _slugify_product(f"{brand}-{name[:35]}")
        link_md = f"[{name}]({url})" if url else name

        block_lines = [f"{i}. {name} — {brand} — {price} €"]
        if product_type:
            block_lines.append(f"   Type produit   : {product_type}")
        if description:
            block_lines.append(f"   Description    : {description[:300]}")
        block_lines.append(f"   Balise image   : {{{{PRODUCT_IMAGE:{slug}}}}}")
        block_lines.append(f"   Lien Markdown  : {link_md}")
        prod_blocks.append("\n".join(block_lines))
    products_block = "\n\n".join(prod_blocks)
    n = len(products)

    prompt = f"""Tu rédiges le corps d'un article de blog d'affiliation en DEUX langues : français ET anglais.

Titre FR de l'article : « {title_fr} »
Titre EN de l'article : « {title_en} »
Thème : {niche_label} — {month_fr} {year}

{n} PRODUITS À PRÉSENTER (dans cet ordre) :

{products_block}

STRUCTURE ATTENDUE (pour chaque langue) :
1. Accroche courte (2-3 phrases) — ton direct, chaleureux, donne envie de lire.
2. Pour CHAQUE produit, dans l'ordre :
   a. La balise image sur sa propre ligne (copie-la exactement telle que fournie — IDENTIQUE en FR et EN)
   b. Un paragraphe de 3-5 phrases dans la langue cible.
      Dans ce paragraphe, cite le nom du produit avec le lien Markdown exact fourni.
3. Conclusion courte (2-3 phrases) + CTA.

RÈGLES ABSOLUES :
- Copie les balises {{{{PRODUCT_IMAGE:...}}}} EXACTEMENT telles qu'elles sont fournies, identiques en FR et EN.
- Utilise les liens Markdown EXACTS fournis pour chaque produit.
- NE JAMAIS INVENTER d'informations non présentes dans le bloc produit ci-dessus (caractéristiques, compatibilités, taille d'écran, modèle de téléphone, etc.).
- Si tu manques d'informations sur un produit, décris uniquement ce que tu sais (type de produit, marque, prix) sans inventer.
- Ton : blog lifestyle, direct, chaleureux.
- 300 à 450 mots par langue.
- PAS de titre Markdown (#) — juste le corps du texte.
- Retourne EXACTEMENT ce format, rien d'autre :

[corps en français ici — 300-450 mots]
===ENGLISH===
[english body here — 300-450 words]"""

    print(f"  📝 Génération corps article bilingue ({OLLAMA_CLOUD_MODEL})…")
    raw = _call_llm(prompt, 3000) or ""
    parts = raw.split("===ENGLISH===", 1)
    fr_body_md = parts[0].strip() if parts else ""
    en_body_md = parts[1].strip() if len(parts) == 2 else ""

    def _fallback_body(lang: str) -> str:
        paras = [
            f"{'Découvrez' if lang == 'fr' else 'Discover'} notre sélection {niche_label} de {month_fr} {year}."
        ]
        for p in products:
            name  = (p.get("name") or "?").strip()
            brand = (p.get("brand") or "?").strip()
            price = p.get("price") or "?"
            url   = p.get("affiliate_url") or p.get("url") or ""
            slug  = _slugify_product(f"{brand}-{name[:35]}")
            link  = f"[{name}]({url})" if url else name
            paras.append(f"{{{{PRODUCT_IMAGE:{slug}}}}}")
            paras.append(
                f"{link} ({brand}, {price} €) "
                f"{'fait partie de nos coups de cœur.' if lang == 'fr' else 'is one of our top picks.'}"
            )
        paras.append(
            f"{'Retrouvez toute la sélection sur' if lang == 'fr' else 'See the full selection on'} "
            f"[MyGoodPick]({SITE_URL})."
        )
        return "\n\n".join(paras)

    if not fr_body_md or len(fr_body_md.split()) < 50:
        fr_body_md = _fallback_body("fr")
    if not en_body_md or len(en_body_md.split()) < 50:
        en_body_md = _fallback_body("en")

    body_html_fr = _markdown_body_to_html(fr_body_md, products, lang="fr")
    body_html_en = _markdown_body_to_html(en_body_md, products, lang="en")
    return body_html_fr, body_html_en


# ══════════════════════════════════════════════════════════════════════════════
# VISUALS — Pinterest 1000×1500 px (HF FLUX.1-schnell + Caveat overlay)
# Reproduit exactement le rendu de pinterest-affiliate-bot/generate_images.py
# ══════════════════════════════════════════════════════════════════════════════

class GenerationError(Exception):
    pass

# ---------------------------------------------------------------------------
# FONT MANAGEMENT — auto-download Caveat if missing
# ---------------------------------------------------------------------------

CAVEAT_URLS = {
    "Caveat-Bold.ttf": [
        "https://github.com/googlefonts/caveat/raw/refs/heads/main/fonts/ttf/Caveat-Bold.ttf",
        "https://cdn.jsdelivr.net/gh/googlefonts/caveat@main/fonts/ttf/Caveat-Bold.ttf",
        "https://fonts.gstatic.com/s/caveat/v18/WnznHAc5bAfYB2QRah7pcpNvOx-pjcJ9eIWpZA.ttf",
    ],
    "Caveat-Regular.ttf": [
        "https://github.com/googlefonts/caveat/raw/refs/heads/main/fonts/ttf/Caveat-Regular.ttf",
        "https://cdn.jsdelivr.net/gh/googlefonts/caveat@main/fonts/ttf/Caveat-Regular.ttf",
        "https://fonts.gstatic.com/s/caveat/v18/WnznHAc5bAfYB2QRah7pcpNvOx-pjfJ9eIWpZA.ttf",
    ],
}

_TTF_MAGIC = (b"\x00\x01\x00\x00", b"\x74\x72\x75\x65", b"\x4F\x54\x54\x4F", b"\x74\x79\x70\x31")


def _is_valid_ttf(data: bytes) -> bool:
    return len(data) > 4 and data[:4] in _TTF_MAGIC


def _download_font(font_file: str, urls: list, dest: Path) -> bool:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/octet-stream, */*"}
    for url in urls:
        try:
            print(f"  [FONTS] ↓ {url}")
            r = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
            r.raise_for_status()
            if not _is_valid_ttf(r.content):
                continue
            dest.write_bytes(r.content)
            print(f"  [FONTS] ✓ {font_file} ({len(r.content) // 1024} Ko)")
            return True
        except Exception:
            continue
    return False


def _ensure_fonts() -> dict:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = {}
    for font_file, urls in CAVEAT_URLS.items():
        font_path = FONTS_DIR / font_file
        if font_path.exists() and _is_valid_ttf(font_path.read_bytes()):
            paths[font_file] = font_path
            continue
        if font_path.exists():
            font_path.unlink()
        if _download_font(font_file, urls, font_path):
            paths[font_file] = font_path
        else:
            paths[font_file] = None
    return paths


def _load_caveat(font_name: str, font_size: int, font_paths: dict) -> ImageFont.FreeTypeFont:
    path = font_paths.get(font_name)
    if path and path.exists():
        try:
            return ImageFont.truetype(str(path), font_size)
        except Exception:
            pass
    for sf in ["/System/Library/Fonts/Helvetica.ttc",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try:
            return ImageFont.truetype(sf, font_size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=font_size)
    except TypeError:
        return ImageFont.load_default()


# Pré-chargement des polices au démarrage
_FONT_PATHS = _ensure_fonts() if _PIL else {}


# ---------------------------------------------------------------------------
# IMAGE GENERATION — HuggingFace FLUX.1-schnell
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(5), wait=wait_fixed(15), retry=retry_if_exception_type(GenerationError))
def _generate_image_hf(prompt: str) -> "Image.Image":
    if not HF_API_TOKEN:
        raise GenerationError("HF_API_TOKEN n'est pas défini")
    NO_TEXT_HEADER = (
        "PURE PHOTOGRAPH with ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, "
        "NO NUMBERS, NO LABELS, NO SIGNS, NO LOGOS, NO WATERMARKS, "
        "NO CAPTIONS, NO WRITING OF ANY KIND anywhere in the image. "
        "All product surfaces must be plain and label-free. "
        "Professional interior photography only. Scene: "
    )
    url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": NO_TEXT_HEADER + prompt.strip(),
               "parameters": {"width": PIN_W, "height": PIN_H}}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if resp.status_code == 503:
            raise GenerationError(f"Modèle en chargement: {resp.text[:120]}")
        if resp.status_code != 200:
            raise GenerationError(f"HF API {resp.status_code}: {resp.text[:120]}")
        return Image.open(BytesIO(resp.content)).convert("RGB")
    except GenerationError:
        raise
    except Exception as e:
        raise GenerationError(f"HF Request Error: {e}")


def _blur_text_regions(img: "Image.Image") -> "Image.Image":
    try:
        import easyocr
        import numpy as np
    except ImportError:
        return img
    try:
        reader = easyocr.Reader(["en", "fr"], gpu=False, verbose=False)
        results = reader.readtext(np.array(img), detail=1)
        if not results:
            return img
        img_out = img.copy()
        for bbox, _text, conf in results:
            if conf < 0.25:
                continue
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            pad = 30
            x0 = max(0, int(min(xs)) - pad)
            y0 = max(0, int(min(ys)) - pad)
            x1 = min(img.width, int(max(xs)) + pad)
            y1 = min(img.height, int(max(ys)) + pad)
            region = img_out.crop((x0, y0, x1, y1))
            for _ in range(3):
                region = region.filter(ImageFilter.GaussianBlur(radius=18))
            img_out.paste(region, (x0, y0))
        return img_out
    except Exception:
        return img


# ---------------------------------------------------------------------------
# TEXT OVERLAY — Pinterest Style (Caveat + highlight blobs)
# ---------------------------------------------------------------------------

def _tw(font: ImageFont.FreeTypeFont, text: str) -> float:
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    return dummy.textlength(text, font=font)


def _wrap_overlay(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.upper().split()
    lines, cur = [], []
    for word in words:
        candidate = " ".join(cur + [word])
        if _tw(font, candidate) > max_w and cur:
            lines.append(" ".join(cur))
            cur = [word]
        else:
            cur.append(word)
    if cur:
        lines.append(" ".join(cur))
    return lines or [text.upper()]


def _autofit(text: str, font_name: str, font_paths: dict,
             max_w: int, max_h: int,
             start: int = 190, minimum: int = 50, spacing: float = 1.20) -> tuple:
    words_upper = text.upper().split()
    for size in range(start, minimum - 1, -2):
        font = _load_caveat(font_name, size, font_paths)
        if max(_tw(font, w) for w in words_upper) > max_w:
            continue
        lines = _wrap_overlay(text, font, max_w)
        line_h = int(size * spacing)
        if len(lines) * line_h <= max_h:
            return font, lines, line_h, size
    font = _load_caveat(font_name, minimum, font_paths)
    lines = _wrap_overlay(text, font, max_w)
    line_h = int(minimum * spacing)
    return font, lines, line_h, minimum


def _add_text_overlay(img: "Image.Image", texte: str, save_to: str) -> str:
    """Overlay Pinterest : gradient sombre + highlight blobs Caveat + ombre + tiret."""
    img = img.convert("RGBA")
    W, H = img.size

    # 1. Gradient sombre en haut
    BAND_H = int(H * 0.48)
    grad_pixels = []
    for row in range(BAND_H):
        t = row / BAND_H
        alpha = int(160 * (1.0 - t ** 0.55))
        grad_pixels.append((8, 6, 5, alpha))
    grad_col = Image.new("RGBA", (1, BAND_H))
    grad_col.putdata(grad_pixels)
    gradient = grad_col.resize((W, BAND_H), Image.Resampling.NEAREST)
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    band.paste(gradient, (0, 0))
    img = Image.alpha_composite(img, band)

    # 2. Autofit texte
    MARGIN_X = int(W * 0.07)
    PAD_TOP = int(H * 0.04)
    PAD_BOT = int(H * 0.04)
    MAX_TXT_W = W - 2 * MARGIN_X
    MAX_TXT_H = BAND_H - PAD_TOP - PAD_BOT

    font, lines, line_h, fsize = _autofit(
        texte, "Caveat-Bold.ttf", _FONT_PATHS,
        max_w=MAX_TXT_W, max_h=MAX_TXT_H,
        start=190, minimum=50, spacing=1.20,
    )

    # 3. Highlight boxes
    HL_PAD = int(fsize * 0.20)
    HL_RADIUS = max(10, int(fsize * 0.22))
    INTER_GAP = int(fsize * 0.22)

    PALETTES = [
        ((10, 8, 6, 230), (255, 255, 255, 255), (20, 15, 10, 255)),
        ((38, 35, 55, 225), (255, 240, 200, 255), (20, 15, 40, 255)),
        ((15, 45, 35, 225), (245, 235, 210, 255), (10, 30, 20, 255)),
        ((90, 40, 35, 220), (255, 240, 215, 255), (60, 20, 15, 255)),
        ((155, 100, 55, 215), (255, 255, 255, 255), (90, 55, 20, 255)),
        ((55, 75, 90, 225), (240, 225, 200, 255), (25, 40, 55, 255)),
        ((130, 90, 85, 220), (255, 250, 240, 255), (80, 50, 45, 255)),
        ((30, 50, 65, 225), (210, 240, 220, 255), (15, 30, 45, 255)),
        ((75, 65, 55, 220), (255, 245, 220, 255), (40, 35, 25, 255)),
        ((180, 155, 120, 215), (30, 25, 15, 255), (120, 100, 70, 255)),
    ]
    rng = random.Random(hash(texte))
    blob_color, text_color, stroke_color = rng.choice(PALETTES)

    # Passe 1 : boîtes relatives
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    text_positions_rel, hl_boxes_rel = [], []
    y = 0
    for line in lines:
        lw = int(_tw(font, line))
        txt_x = (W - lw) // 2
        tbbox = dummy.textbbox((txt_x, y), line, font=font)
        text_positions_rel.append((txt_x, y))
        hl_boxes_rel.append([
            tbbox[0] - HL_PAD,
            tbbox[1] - HL_PAD + INTER_GAP // 2,
            tbbox[2] + HL_PAD,
            tbbox[3] + HL_PAD - INTER_GAP // 2,
        ])
        y += line_h

    # Passe 2 : centrer à 35 % de la hauteur
    actual_block_h = hl_boxes_rel[-1][3] - hl_boxes_rel[0][1]
    target_center_y = int(H * 0.35)
    shift = target_center_y - actual_block_h // 2 - hl_boxes_rel[0][1]

    text_positions = [(tx, ty + shift) for tx, ty in text_positions_rel]
    hl_boxes = [[hx0, hy0 + shift, hx1, hy1 + shift] for hx0, hy0, hx1, hy1 in hl_boxes_rel]

    # 4. Dessiner les highlight blobs (rounded_rectangle par ligne)
    hl_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hl_draw = ImageDraw.Draw(hl_layer)
    for hx0, hy0, hx1, hy1 in hl_boxes:
        try:
            hl_draw.rounded_rectangle([hx0, hy0, hx1, hy1], radius=HL_RADIUS, fill=blob_color)
        except AttributeError:
            hl_draw.rectangle([hx0, hy0, hx1, hy1], fill=blob_color)
    img = Image.alpha_composite(img, hl_layer)

    # 5. Ombre portée
    sh_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh_draw = ImageDraw.Draw(sh_layer)
    sh_off = max(3, fsize // 32)
    sh_blur = max(4, fsize // 20)
    for (txt_x, txt_y), line in zip(text_positions, lines):
        sh_draw.text((txt_x + sh_off, txt_y + sh_off), line, font=font, fill=(0, 0, 0, 180))
    sh_layer = sh_layer.filter(ImageFilter.GaussianBlur(radius=sh_blur))
    img = Image.alpha_composite(img, sh_layer)

    # 6. Texte principal
    draw = ImageDraw.Draw(img)
    stroke_w = max(2, fsize // 55)
    for (txt_x, txt_y), line in zip(text_positions, lines):
        draw.text((txt_x, txt_y), line, font=font,
                  fill=text_color, stroke_width=stroke_w, stroke_fill=stroke_color)

    # 7. Tiret décoratif
    last_box_bottom = hl_boxes[-1][3]
    dash_y = last_box_bottom + int(fsize * 0.25)
    dash_hw = int(W * 0.055)
    dash_cx = W // 2
    dash_th = max(2, fsize // 60)
    draw.line([(dash_cx - dash_hw, dash_y), (dash_cx + dash_hw, dash_y)],
              fill=(*text_color[:3], 190), width=dash_th)
    dot_r = dash_th + 1
    for dx in [dash_cx - dash_hw, dash_cx + dash_hw]:
        draw.ellipse([dx - dot_r, dash_y - dot_r, dx + dot_r, dash_y + dot_r],
                     fill=(*text_color[:3], 170))

    # 8. Sauvegarde
    img = img.convert("RGB")
    img.save(save_to, "JPEG", quality=98, optimize=True)
    return save_to


def _generate_pin_image(prompt: str, overlay_text: str, save_to: Path) -> str:
    """Génère une image HF + blur texte + overlay Caveat. Fallback gradient si HF échoue."""
    try:
        base_img = _generate_image_hf(prompt)
        base_img = _blur_text_regions(base_img)
    except Exception as e:
        print(f"     ⚠️  HF fallback gradient: {e}")
        base_img = Image.new("RGB", (PIN_W, PIN_H))
        draw = ImageDraw.Draw(base_img)
        for y in range(PIN_H):
            t = y / PIN_H
            draw.line([(0, y), (PIN_W, y)], fill=(
                int(14 + (22 - 14) * t), int(20 + (32 - 20) * t), int(36 + (56 - 36) * t)))

    base_img = base_img.resize((PIN_W, PIN_H), Image.LANCZOS)
    base_img.save(str(save_to), "JPEG", quality=90)
    _add_text_overlay(Image.open(str(save_to)), overlay_text, str(save_to))
    return str(save_to)


def generate_visuals(slug: str, title: str, nb_products: int, niche: str,
                     niche_label: str, month_fr: str, year: str,
                     products: list, taxonomy: dict, nb_visuals: int,
                     overlay_texts_fr: list = None,
                     overlay_texts_en: list = None,
                     board_name_fr: str = "",
                     board_name_en: str = "") -> dict:
    """Génère nb_visuals × 2 pins (FR + EN) à partir d'un seul fond HF par variante.
    Le même fond reçoit un overlay de texte différent selon la langue.
    Retourne {"fr": [paths…], "en": [paths…]}.
    """
    niche_cfg = taxonomy.get("niche_config", {}).get(niche, {})

    # ── Prompt niche-specific : on construit un prompt visuel ciblé sur ce que
    #    l'utilisateur Pinterest verra concrètement, pas une chambre générique.
    _NICHE_VISUAL_HINTS: dict[str, str] = {
        "gaming_setup": (
            "ultra-wide gaming battlestation with glowing RGB monitors, "
            "mechanical keyboard and gaming chair, dark room with LED accent lighting, "
            "high-end peripheral accessories arranged on a sleek desk"
        ),
        "audio_hi_fi": (
            "audiophile hi-fi listening room with large floor-standing speakers, "
            "turntable on a solid wood shelf, coaxial cables, warm amber lamp light"
        ),
        "living_room_storage": (
            "modern living room with elegant built-in shelving and storage units, "
            "neatly organized books and decorative objects, natural light"
        ),
        "home_office_setup": (
            "bright minimalist home office desk setup with dual monitors, ergonomic chair, "
            "cable management tray, indoor plants, white and wood tones"
        ),
        "cable_management": (
            "perfectly organized desk with cable management channels and velcro ties, "
            "clean white surface, hidden wires, sleek modern aesthetic"
        ),
        "small_space_solutions": (
            "smart small apartment organization with multifunctional furniture, "
            "wall-mounted shelving, compact storage solutions, airy Scandinavian style"
        ),
        "smart_home": (
            "modern smart home interior with visible smart speaker, connected light bulbs, "
            "security camera on wall, tablet dashboard, minimalist living room"
        ),
        "entryway_decor": (
            "stylish entryway with smart lock on wooden door, coat hooks, "
            "illuminated keypad, welcoming warm lighting, clean modern design"
        ),
        "eco_home": (
            "eco-friendly home with plants, solar panel visible through window, "
            "energy monitor display, reusable materials, warm sustainable decor"
        ),
        "cozy_lighting": (
            "cozy bedroom with warm string lights, bedside lamp casting golden glow, "
            "soft linen pillows, candles, intimate atmospheric evening ambiance"
        ),
        "bedroom_essentials": (
            "serene Scandinavian bedroom with neatly made bed, natural fiber textiles, "
            "minimalist nightstands, morning soft light through linen curtains"
        ),
        "closet_organization": (
            "beautifully organized walk-in closet with matching velvet hangers, "
            "folded clothes in uniform stacks, transparent storage boxes, soft lighting"
        ),
        "kids_room": (
            "bright playful kids bedroom with colorful storage bins, "
            "wooden toy shelves, educational wall art, safe rounded furniture"
        ),
        "kitchen_organization": (
            "sparkling organized kitchen with glass jar pantry containers, "
            "magnetic knife strip, pull-out drawer organizers, clean countertops"
        ),
        "bathroom_storage": (
            "spa-like bathroom with bamboo shelf organizer, neatly rolled towels, "
            "glass apothecary jars, soft lighting, white marble surfaces"
        ),
        "outdoor_living": (
            "beautiful outdoor garden or terrace with modern furniture, "
            "outdoor security camera on wall, garden hose, lush green plants, "
            "warm summer daylight, wooden deck"
        ),
        "mobile_nomade": (
            "nomad travel setup with smartphone stand, protective phone cases, "
            "portable charger, earbuds, flat-lay on minimalist white background"
        ),
    }
    visual_hint = niche_cfg.get(
        "image_style",
        _NICHE_VISUAL_HINTS.get(niche, f"lifestyle product photography for {niche_label}")
    )

    # On mentionne explicitement les produits principaux dans le prompt
    product_names = ", ".join(
        p.get("name", "")[:40] for p in products[:3] if p.get("name")
    )
    product_mention = (
        f"featuring products like: {product_names}. " if product_names else ""
    )

    slug_safe = re.sub(r"[^a-z0-9-]", "", slug.lower())[:42]

    # Un dossier par article — web-accessible via Next.js /public
    slug_dir = ROOT / "public" / "local_pins" / slug_safe
    slug_dir.mkdir(parents=True, exist_ok=True)

    nb = min(nb_visuals, 3)

    # Overlays par défaut
    if not overlay_texts_fr:
        overlay_texts_fr = [title] * nb
    if not overlay_texts_en:
        overlay_texts_en = [title] * nb

    # Prompts image ciblés sur la niche — utilisés seulement en production
    _base = (
        f"Photorealistic vertical Pinterest image 1000x1500, {visual_hint}. "
        f"{product_mention}"
        f"ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, NO LOGOS, NO WATERMARKS, "
        f"NO PEOPLE anywhere in the image. Professional photography, "
        f"sharp focus, vibrant colors, editorial quality."
    )
    _prompt_pool = [
        f"{_base} Wide establishing shot, golden morning light, aspirational lifestyle.",
        f"{_base} Warm afternoon light, cinematic close-up of key product, rich material detail.",
        f"{_base} Soft overhead light, clean flat-lay composition, neutral background.",
        f"{_base} Dramatic side lighting, moody editorial atmosphere, deep shadows.",
        f"{_base} Bright airy feel, window light, Scandinavian minimalism.",
        f"{_base} Cozy evening ambiance, warm lamplight, intimate lifestyle scene.",
    ]

    def _get_base_img(prompt: str) -> "Image.Image":
        """Retourne l'image de fond : placeholder en test, HF en production."""
        if not production_workflow:
            ph = ROOT / "public" / "placeholder.jpg"
            if ph.exists():
                return Image.open(ph).convert("RGB").resize((PIN_W, PIN_H), Image.LANCZOS)
        img = _generate_image_hf(prompt)
        img = _blur_text_regions(img)
        return img.resize((PIN_W, PIN_H), Image.LANCZOS)

    paths_fr: list = []
    paths_en: list = []
    bg_web_paths: list = []  # contient uniquement le chemin cover.jpg (fond sans overlay) pour la galerie

    combo_idx = 0
    for i in range(nb):
        variant = f"pin{i + 1}"
        fr_path = slug_dir / f"{variant}_fr.jpg"
        en_path = slug_dir / f"{variant}_en.jpg"
        ov_fr = overlay_texts_fr[i] if i < len(overlay_texts_fr) else title
        ov_en = overlay_texts_en[i] if i < len(overlay_texts_en) else title

        # ── Version FR ────────────────────────────────────────────────────
        print(f"  🖼️  Visuel {variant} FR…")
        try:
            base_fr = _get_base_img(_prompt_pool[combo_idx % len(_prompt_pool)])
            # Premier visuel : sauvegarder le fond brut (sans overlay) comme image de couverture
            if i == 0 and not bg_web_paths:
                cover_path = slug_dir / "cover.jpg"
                base_fr.copy().save(str(cover_path), "JPEG", quality=85)
                bg_web_paths.append(f"/local_pins/{slug_safe}/cover.jpg")
            _add_text_overlay(base_fr, ov_fr, str(fr_path))
            print(f"     → [FR] {fr_path.name}  (\"{ov_fr[:40]}\")")
            paths_fr.append(str(fr_path))
        except Exception as e:
            print(f"  ⚠️  Visuel {variant} FR échoué : {e}")
        combo_idx += 1

        # ── Version EN ────────────────────────────────────────────────────
        print(f"  🖼️  Visuel {variant} EN…")
        try:
            base_en = _get_base_img(_prompt_pool[combo_idx % len(_prompt_pool)])
            _add_text_overlay(base_en, ov_en, str(en_path))
            print(f"     → [EN] {en_path.name}  (\"{ov_en[:40]}\")")
            paths_en.append(str(en_path))
        except Exception as e:
            print(f"  ⚠️  Visuel {variant} EN échoué : {e}")
        combo_idx += 1

    return {"fr": paths_fr, "en": paths_en, "bg": bg_web_paths}
# ══════════════════════════════════════════════════════════════════════════════
# R2 UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def upload_to_r2(image_path: Path, key: str) -> str:
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("  ⚠️  boto3 non installé — pip install boto3")
        return ""

    if not all([R2_PUBLIC_URL, R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        print("  ⚠️  Variables R2 manquantes")
        return ""

    try:
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        with open(image_path, "rb") as f:
            client.put_object(
                Bucket=R2_BUCKET_NAME, Key=key, Body=f.read(),
                ContentType="image/jpeg",
                CacheControl="public, max-age=2592000, immutable",
            )
        public_url = f"{R2_PUBLIC_URL}/{key}"
        print(f"  ☁️  R2 → {public_url}")
        return public_url
    except Exception as e:
        print(f"  ⚠️  Upload R2 échoué : {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# PINTEREST PUBLISH
# ══════════════════════════════════════════════════════════════════════════════

def _publish_pin(board_id: str, title: str, description: str,
                 media_url: str, link: str) -> dict:
    if not PINTEREST_ACCESS_TOKEN:
        raise RuntimeError("PINTEREST_ACCESS_TOKEN manquant")
    r = requests.post(
        f"{PINTEREST_API_BASE}/pins",
        headers={"Authorization": f"Bearer {PINTEREST_ACCESS_TOKEN}",
                 "Content-Type": "application/json"},
        json={
            "board_id": board_id,
            "title": title[:100],
            "description": description[:500],
            "media_source": {"source_type": "image_url", "url": media_url},
            "link": link,
        },
        timeout=30,
    )
    if r.status_code == 401:
        raise RuntimeError("Pinterest token expiré — refresh_pinterest_token.py")
    if r.status_code == 429:
        raise RuntimeError("Pinterest rate limit (429)")
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Pinterest API {r.status_code}: {r.text[:300]}")
    return r.json()


def publish_visuals_pinterest(
        slug: str, title: str, niche: str,
        niche_label: str, month: str,
        pin_paths: dict, taxonomy: dict,
        pin_title: str = None,
        pin_description: str = None,
        board_id_fr: str = None,
        board_id_en: str = None,
        pin_content: dict = None,
        publish_to_pinterest: bool = False) -> list:
    """Publie ou confirme les pins FR → board FR et EN → board EN.
    pin_paths = {"fr": [...chemins FR...], "en": [...chemins EN...]}
    En mode local les fichiers sont déjà sauvegardes par generate_visuals().
    """
    article_url = f"{SITE_URL}/top/{slug}"
    final_title_fr = pin_title or title
    en_data        = (pin_content or {}).get("en", {})
    final_title_en = en_data.get("pin_title") or final_title_fr
    desc_en        = en_data.get("description") or pin_description or title

    if not pin_description:
        niche_cfg = taxonomy.get("niche_config", {}).get(niche, {})
        pin_description = niche_cfg.get("pinterest_description_fr", "").format(
            n=sum(len(v) for v in pin_paths.values()),
            month=MONTH_FR.get(month.split("-")[1], ""),
            year=month.split("-")[0],
        ) or f"{title} — {niche_label}"

    fr_paths = pin_paths.get("fr", [])
    en_paths = pin_paths.get("en", [])
    published = []

    # ── Mode local : les fichiers sont déjà enregistrés dans les bons dossiers ──
    if not publish_to_pinterest:
        for lang, paths in [("fr", fr_paths), ("en", en_paths)]:
            for p in paths:
                print(f"  💾 [{lang.upper()}] → {p}")
                published.append({"variant": Path(p).stem, "r2_url": p, "pin_id": ""})
        return published

    # ── Mode production : upload R2 + publish FR + publish EN ───────────────
    if not PINTEREST_ACCESS_TOKEN:
        print("  ⚠️  PINTEREST_ACCESS_TOKEN manquant — publication ignorée")
        return []

    for i, (fr_path, en_path) in enumerate(zip(fr_paths, en_paths)):
        variant = f"pin{i + 1}"

        # Upload image FR
        r2_url_fr = upload_to_r2(Path(fr_path), f"pins/top/{slug}_{variant}_fr.jpg")
        # Upload image EN
        r2_url_en = upload_to_r2(Path(en_path), f"pins/top/{slug}_{variant}_en.jpg")

        if board_id_fr and r2_url_fr:
            try:
                pin = _publish_pin(
                    board_id=board_id_fr, title=final_title_fr,
                    description=pin_description, media_url=r2_url_fr, link=article_url,
                )
                pid = pin.get("id", "")
                print(f"  📌 Pin FR publié ({variant}): {pid}")
                published.append({"variant": variant + "_fr", "r2_url": r2_url_fr, "pin_id": pid})
                sb_upsert("pinterest_pins", {
                    "pin_id": pid, "image_url": r2_url_fr,
                    "pin_url": f"https://www.pinterest.com/pin/{pid}/",
                    "title": final_title_fr[:100], "description": pin_description[:500],
                    "link_to_article": article_url,
                    "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "status": "published",
                })
                time.sleep(15)
            except Exception as e:
                print(f"  ⚠️  Pin FR ({variant}) échoué : {e}")

        if board_id_en and r2_url_en:
            try:
                pin_en = _publish_pin(
                    board_id=board_id_en, title=final_title_en,
                    description=desc_en, media_url=r2_url_en, link=article_url,
                )
                pid_en = pin_en.get("id", "")
                print(f"  📌 Pin EN publié ({variant}): {pid_en}")
                published.append({"variant": variant + "_en", "r2_url": r2_url_en, "pin_id": pid_en})
                sb_upsert("pinterest_pins", {
                    "pin_id": pid_en, "image_url": r2_url_en,
                    "pin_url": f"https://www.pinterest.com/pin/{pid_en}/",
                    "title": final_title_en[:100], "description": desc_en[:500],
                    "link_to_article": article_url,
                    "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "status": "published",
                })
                if i < len(fr_paths) - 1:
                    time.sleep(30)
            except Exception as e:
                print(f"  ⚠️  Pin EN ({variant}) échoué : {e}")

    return published


# ══════════════════════════════════════════════════════════════════════════════
# ARTICLE ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════

def run_article(niche: str, taxonomy: dict, trends: dict, args) -> bool:
    year, mo = args.month.split("-")
    month_fr = MONTH_FR.get(mo, mo)
    niche_cfg = taxonomy.get("niche_config", {}).get(niche, {})
    niche_label = niche_cfg.get("label_fr", niche.replace("_", " "))
    niche_label_en = niche_cfg.get("label_en") or _NICHE_LABEL_EN.get(niche, niche.replace("_", " ").title())
    slug_prefix = niche_cfg.get("page_slug_prefix", niche.replace("_", "-"))
    slug = f"{slug_prefix}-{args.month}"

    print(f"\n  🔍 Niche : {niche}  ({niche_label})")

    # 1. Produits
    nb_prod = args.nb_products or nb_products_per_article
    products = fetch_diverse_products(niche, count=nb_prod, taxonomy=taxonomy)
    if len(products) < min(3, nb_prod):
        print(f"  ⚠️  Seulement {len(products)} produits (min {min(3, nb_prod)} requis) — article ignoré")
        return False

    cats = [p.get("category_slug", "") for p in products if p.get("category_slug")]
    category_slug = max(set(cats), key=cats.count) if cats else niche

    # 2. Contenu LLM article
    content = generate_content(niche, niche_label, month_fr, year, products, taxonomy)
    print(f"  📝 Titre article : {content['title']}")

    # 2b. Contenu Pinterest (titre pin, description+hashtags, overlay)
    print(f"  📌 Génération contenu Pinterest (PINS_WRITING_LLM)…")
    pin_content = generate_pin_content(
        content["title"], niche_label, nb_prod, products, month_fr, year
    )
    print(f"  📌 Titre pin  : {pin_content['pin_title']}")

    # Board routing
    board_name_fr, board_id_fr = get_board_for_niche(niche, "fr")
    board_name_en, board_id_en = get_board_for_niche(niche, "en")
    print(f"  🗂  Board FR : {board_name_fr} [{board_id_fr or 'ID à remplir'}]")
    print(f"  🗂  Board EN : {board_name_en} [{board_id_en or 'ID à remplir'}]")

    # 3. Visuels
    pin_paths = []
    if args.create_visuals:
        if not _PIL:
            print("  ⚠️  Pillow non disponible — pip install Pillow")
        else:
            nb_vis = max(1, min(args.nb_visuals, 3))
            print(f"\n  🎨 Génération de {nb_vis} × 2 visuels (FR + EN, fonds distincts)…")

            # Overlays variés : hero LLM + fallbacks croissants pour chaque variante
            _top_p_fr = f"Top {nb_prod} {niche_label}"
            _top_p_en = f"Top {nb_prod} {niche_label.title()} picks"
            _ov_fr_pool = [
                pin_content["fr"]["overlay_hero"],
                content["title"][:55] if len(content["title"]) <= 55 else _top_p_fr,
                _top_p_fr,
            ]
            _ov_en_pool = [
                pin_content["en"]["overlay_hero"],
                content.get("title_en", "")[:55] or _top_p_en,
                _top_p_en,
            ]
            pin_paths = generate_visuals(
                slug, content["title"], nb_prod, niche, niche_label,
                month_fr, year, products, taxonomy, nb_vis,
                overlay_texts_fr=_ov_fr_pool[:nb_vis],
                overlay_texts_en=_ov_en_pool[:nb_vis],
                board_name_fr=board_name_fr,
                board_name_en=board_name_en,
            )

    # 4. Enrichir les données produits pour le JSON
    enriched = [
        {
            "id": p["id"],
            "name": p.get("name"),
            "brand": p.get("brand"),
            "price": p.get("price"),
            "url": p.get("affiliate_url"),
            "partner": p.get("merchant_key"),
            "image_url": p.get("image_url"),
            "blurb_fr": content["blurbs"][i] if i < len(content["blurbs"]) else "",
        }
        for i, p in enumerate(products)
    ]

    # 5. Construire le contenu complet de l'article
    article_content = json.dumps({
        "category_slug": category_slug,
        "subcategory": niche_label,
        "subcategory_en": niche_label_en,
        "keyword": niche,
        "title_en": content.get("title_en", ""),
        "intro_fr": content["intro"],
        "intro_en": content.get("intro_en", ""),
        "body_html_fr": content.get("body_html_fr", ""),
        "body_html_en": content.get("body_html_en", ""),
        "products": enriched,
        "month": args.month,
    }, ensure_ascii=False)

    article_url = f"{SITE_URL}/top/{slug}"
    ids_products_used = [p["id"] for p in products]

    row = {
        "slug": slug,
        "url": article_url,
        "title": content["title"],
        "ids_products_used": ids_products_used,
        "content": article_content,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if args.dry_run:
        print(f"\n  [DRY-RUN] Slug        : {slug}")
        print(f"  [DRY-RUN] URL         : {article_url}")
        print(f"  [DRY-RUN] Titre art.  : {content['title']}")
        print(f"  [DRY-RUN] Titre pin   : {pin_content['pin_title']}")
        print(f"  [DRY-RUN] Titre pin EN: {pin_content.get('en', {}).get('pin_title', '')}")
        print(f"  [DRY-RUN] Description : {pin_content['description'][:100]}…")
        print(f"  [DRY-RUN] Overlay 1   : {pin_content['overlay_texts'][0]}")
        print(f"  [DRY-RUN] Intro FR    : {content['intro'][:120]}…")
        print(f"  [DRY-RUN] Intro EN    : {content.get('intro_en', '')[:120]}…")
        for j, p in enumerate(enriched):
            print(f"    #{j+1} {p['name'][:55]} — {p.get('price','?')} €")
        if pin_paths:
            print(f"  [DRY-RUN] Images : {[Path(p).name for p in pin_paths]}")
        return True

    ok = sb_upsert("top_articles", row, on_conflict="slug")
    if ok:
        print(f"  ✅ Enregistré : {slug}")

    # Écriture des fichiers debug en mode local
    if not production_workflow:
        _slug_safe = re.sub(r"[^a-z0-9-]", "", slug.lower())[:42]
        _slug_dir = ROOT / "public" / "local_pins" / _slug_safe
        _slug_dir.mkdir(parents=True, exist_ok=True)

        # article.txt — inputs LLM + article généré
        article_lines = [
            f"NICHE: {niche}", f"NICHE_LABEL: {niche_label}", f"MOIS: {args.month}", "",
            f"TITRE FR: {content['title']}", f"TITRE EN: {content.get('title_en', '')}", "",
            "--- INTRO FR ---", content["intro"], "",
            "--- INTRO EN ---", content.get("intro_en", ""), "",
            "--- ARTICLE HTML FR ---", content.get("body_html_fr", ""), "",
            "--- ARTICLE HTML EN ---", content.get("body_html_en", ""),
        ]
        (_slug_dir / "article.txt").write_text("\n".join(article_lines), encoding="utf-8")

        # pin.txt — titre pin, description, overlay, lien affilié
        pin_lines = [
            f"PIN TITLE FR: {pin_content['fr']['pin_title']}",
            f"PIN TITLE EN: {pin_content['en']['pin_title']}",
            f"OVERLAY FR: {pin_content['fr']['overlay_hero']}",
            f"OVERLAY EN: {pin_content['en']['overlay_hero']}",
            "",
            "--- DESCRIPTION FR ---",
            pin_content["fr"]["description"],
            "",
            "--- DESCRIPTION EN ---",
            pin_content["en"]["description"],
            "",
            f"LIEN ARTICLE: {article_url}",
            "",
            "--- LIENS AFFILIÉS ---",
        ]
        for p in products:
            aff = p.get("affiliate_url") or p.get("url") or "#"
            pin_lines.append(f"  {p.get('name', '?')} → {aff}")
        (_slug_dir / "pin.txt").write_text("\n".join(pin_lines), encoding="utf-8")
        print(f"  📄 article.txt + pin.txt → {_slug_dir}")

    # 6. Publication Pinterest (ou confirmation de sauvegarde locale)
    if pin_paths and any(pin_paths.values()):
        n_fr = len(pin_paths.get("fr", []))
        n_en = len(pin_paths.get("en", []))
        label = "Publication Pinterest" if args.publish_to_pinterest else "Sauvegarde locale"
        print(f"\n  📌 {label} ({n_fr} FR + {n_en} EN = {n_fr + n_en} pins)…")
        published = publish_visuals_pinterest(
            slug, content["title"], niche, niche_label, args.month, pin_paths, taxonomy,
            pin_title=pin_content["pin_title"],
            pin_description=pin_content["description"],
            board_id_fr=board_id_fr,
            board_id_en=board_id_en,
            pin_content=pin_content,
            publish_to_pinterest=args.publish_to_pinterest,
        )
        if published and args.publish_to_pinterest:
            r2_urls = [p["r2_url"] for p in published if p.get("r2_url")]
            sb_patch("top_articles", f"slug=eq.{slug}", {"pin_images": json.dumps(r2_urls)})
        else:
            bg_web = pin_paths.get("bg", [])
            if bg_web:
                sb_patch("top_articles", f"slug=eq.{slug}", {"pin_images": json.dumps(bg_web)})
                print(f"  🖼️  pin_images local mis à jour : {bg_web}")

    return ok


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Génère des articles Top N + visuels Pinterest")
    parser.add_argument("--count", type=int, default=1, help="Nombre d'articles (défaut: 1)")
    parser.add_argument("--nb-products", type=int, default=None,
                        help=f"Produits par article (défaut: {nb_products_per_article} via settings.py)")
    parser.add_argument("--month", default=None,
                        help="Mois cible YYYY-MM (défaut: mois courant)")
    parser.add_argument("--niche", default=None, help="Forcer une niche spécifique")
    parser.add_argument("--create-visuals", dest="create_visuals", action="store_true", default=True)
    parser.add_argument("--no-visuals", dest="create_visuals", action="store_false",
                        help="Pas de génération visuelle")
    parser.add_argument("--nb-visuals", type=int, default=2, help="Visuels par article (1-3, défaut: 2)")
    parser.add_argument("--publish-to-pinterest", dest="publish_to_pinterest",
                        action="store_true", default=False,
                        help="Publier les pins sur Pinterest + upload R2 (indépendant de settings.py)")
    parser.add_argument("--no-publish", action="store_true",
                        help="Forcer sauvegarde locale même si production_workflow=True")
    parser.add_argument("--no-trends", action="store_true", help="Ignorer les tendances Pinterest")
    parser.add_argument("--dry-run", action="store_true", help="Aucune écriture")
    args = parser.parse_args()

    if not args.month:
        args.month = datetime.now().strftime("%Y-%m")

    check_supabase()

    # Résumé config
    llm_info = f"Ollama Cloud ({OLLAMA_CLOUD_MODEL})" if OLLAMA_CLOUD_API_KEY else "template fallback"
    hf_info = ("HF FLUX.1-schnell" if HF_API_TOKEN else "gradient fallback") if args.create_visuals else "désactivé"
    publish_mode = "Pinterest + R2" if args.publish_to_pinterest else "local seulement"
    nb_prod = args.nb_products or nb_products_per_article
    print(f"\n{'═'*62}")
    print(f"  🏆  create_and_post_top_products.py  —  Top {nb_prod}  —  {args.month}")
    print(f"  LLM     : {llm_info}")
    print(f"  Images  : {hf_info}  ({args.nb_visuals} par article)")
    print(f"  Trends  : {'Pinterest FR/US/GB/DE' if not args.no_trends else 'désactivés'}")
    print(f"  Publish : {publish_mode}")
    if args.dry_run:
        print("  Mode    : DRY-RUN")
    print(f"{'═'*62}\n")

    taxonomy = _load_taxonomy()

    # Pré-comptage des produits par niche
    nb_prod = args.nb_products or nb_products_per_article
    print("📊 Comptage des produits par niche…")
    niche_counts = _niche_product_counts(taxonomy)

    # Tendances Pinterest
    trends = {}
    if not args.no_trends:
        print("📈 Récupération des tendances Pinterest…")
        trends = fetch_pinterest_trends()

    total = ok = 0
    used_niches: set = set()
    max_attempts = args.count * 5

    # Exclure les niches déjà publiées ce mois (évite d'écraser un article existant)
    if not args.dry_run:
        try:
            published = sb_get("top_articles", f"slug=like.*-{args.month}&select=slug")
            published_slugs = {r["slug"] for r in published}
            niche_config = taxonomy.get("niche_config", {})
            for _niche, _cfg in niche_config.items():
                _pfx = _cfg.get("page_slug_prefix", _niche.replace("_", "-"))
                if f"{_pfx}-{args.month}" in published_slugs:
                    used_niches.add(_niche)
            if used_niches:
                print(f"  ⏭️  {len(used_niches)} niche(s) déjà publiée(s) ce mois — exclues")
        except Exception as e:
            print(f"  ⚠️  Impossible de récupérer les articles existants : {e}")

    for attempt in range(1, max_attempts + 1):
        if ok >= args.count:
            break

        forced = args.niche if attempt == 1 else None
        print(f"\n{'─'*62}")
        print(f"  [Article {ok+1}/{args.count}] Tentative {attempt}/{max_attempts} — Sélection de niche…")
        niche = pick_niche(taxonomy, trends, forced=forced, exclude=used_niches,
                           niche_counts=niche_counts, min_products=min(3, nb_prod))
        if niche is None:
            print("  ⚠️  Toutes les niches épuisées — arrêt")
            break
        used_niches.add(niche)

        total += 1
        success = run_article(niche, taxonomy, trends, args)
        if success:
            ok += 1
            taxonomy.setdefault("last_used", {})[niche] = datetime.now().isoformat()
            if not args.dry_run:
                _save_taxonomy(taxonomy)

        if ok < args.count and attempt < max_attempts:
            time.sleep(8)

    print(f"\n{'═'*62}")
    print(f"  ✅  {ok}/{total} articles générés — {args.month}")
    if args.dry_run:
        print("  (dry-run : aucun enregistrement)")
    print(f"{'═'*62}\n")


if __name__ == "__main__":
    main()
