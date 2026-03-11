#!/usr/bin/env python3
"""
generate-lifestyle-article.py — Articles "Top N incontournables pour [espace de vie]"
=======================================================================================

DEUX TYPES D'ARTICLES (--mode) :

  top5-lifestyle  (défaut)
      "Top 5 incontournables pour votre chambre en mars 2026"
      → Produits DIVERSIFIÉS issus d'un même univers de vie
        (chambre, salon, bureau, gaming, extérieur…)
      → Guidés par les tendances Pinterest + rotation équilibrée des niches

  top5-product
      Délègue vers generate-top5.py (comparatif produits identiques)
      "Top 5 meilleures souris gaming de mars 2026"

PIPELINE top5-lifestyle :
  1.  Charge config/lifestyle_niches.json
  2.  Récupère les tendances Pinterest FR/US/GB/DE (fallback gracieux si hors-ligne)
  3.  Sélectionne une niche via scoring pondéré (saison × tendances × rotation)
  4.  Marque la niche utilisée dans le JSON (anti-répétition)
  5.  Récupère 5 produits DIVERSIFIÉS via requêtes ILIKE ciblées (1 type par slot)
  6.  LLM (Ollama Cloud minimax) : titre + intro + blurbs individuels
  7.  Upsert dans lifestyle_articles (Supabase)
  8.  Génère N visuels Pinterest 1000×1500 px (HF FLUX.1-schnell + Pillow overlay)
       - Visuel 1 : "Hero"       — ambiance générale niche + titre article
       - Visuel 2 : "Spotlight"  — focus produit #1 avec prix
       - Visuel 3 : "Checklist"  — liste des 5 produits sur fond sombre (no HF)
  9.  Sauvegarde les images localement dans output/lifestyle_pins/

USAGE :
    # Niche choisie automatiquement
    python3 scripts/generate-lifestyle-article.py

    # Forcer une niche
    python3 scripts/generate-lifestyle-article.py --niche smart_home

    # Mode test (pas d'écriture DB, génère quand même les images)
    python3 scripts/generate-lifestyle-article.py --dry-run

    # Mode test total (pas d'écriture, pas d'images HF)
    python3 scripts/generate-lifestyle-article.py --dry-run --no-images

    # Paramétrage avancé
    python3 scripts/generate-lifestyle-article.py --pins-count 3 --month 2026-03

    # Déléguer au script comparatif
    python3 scripts/generate-lifestyle-article.py --mode top5-product

VARIABLES D'ENV (.env.local) :
    NEXT_PUBLIC_SUPABASE_URL     — URL Supabase
    SUPABASE_SERVICE_ROLE_KEY    — Clé service role (pour les upserts)
    OLLAMA_CLOUD_API_KEY         — Ollama Cloud (minimax-m2.5:cloud)
    OLLAMA_CLOUD_HOST            — défaut: https://api.ollama.com
    HF_API_TOKEN ou HF_TOKEN     — Hugging Face (génération FLUX.1-schnell)
    PINTEREST_ACCESS_TOKEN       — OAuth2 Pinterest (tendances)
    PINTEREST_API_BASE           — défaut: https://api.pinterest.com/v5
    SITE_URL                     — défaut: https://affili-compare.com
"""

import argparse
import io
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

# ── Imports ───────────────────────────────────────────────────────────────────
try:
    import requests
except ImportError:
    print("❌  pip install requests")
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:
    print("❌  pip install Pillow")
    sys.exit(1)

# ── Paths & .env loading ──────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent

for _env_file in (ROOT / ".env.local", ROOT / ".env"):
    if _env_file.exists():
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                k, _, v = _line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL    = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY    = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
OLLAMA_API_KEY  = os.environ.get("OLLAMA_CLOUD_API_KEY", "")
OLLAMA_HOST     = os.environ.get("OLLAMA_CLOUD_HOST", "https://api.ollama.com").rstrip("/")
OLLAMA_MODEL    = os.environ.get("OLLAMA_CLOUD_MODEL", "minimax-m2.5:cloud")
if OLLAMA_MODEL == "gemini-3-flash-preview:cloud":
    OLLAMA_MODEL = "minimax-m2.5:cloud"
HF_TOKEN        = os.environ.get("HF_API_TOKEN", "") or os.environ.get("HF_TOKEN", "")
PINTEREST_TOKEN = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
PINTEREST_BASE  = os.environ.get("PINTEREST_API_BASE", "https://api.pinterest.com/v5").rstrip("/")
SITE_URL        = os.environ.get("SITE_URL", "https://affili-compare.com").rstrip("/")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌  NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY requis dans .env.local")
    sys.exit(1)

# ── Config paths ──────────────────────────────────────────────────────────────
NICHES_CFG  = ROOT / "config" / "lifestyle_niches.json"
OUTPUT_DIR  = ROOT / "output" / "lifestyle_pins"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Fonts: priorité pinterest-affiliate-bot, sinon affili-compare, sinon système
_FONTS_CANDIDATES = [
    ROOT.parent / "pinterest-affiliate-bot" / "assets" / "fonts",
    ROOT / "assets" / "fonts",
]
FONTS_DIR = next((p for p in _FONTS_CANDIDATES if p.exists()), Path("/System/Library/Fonts"))

# Pinterest image dimensions (format 2:3)
PIN_W, PIN_H = 1000, 1500

# Regions for trends
TREND_REGIONS = ["FR", "US", "GB", "DE"]
TREND_TYPES   = ["growing", "monthly", "yearly"]

MONTH_FR = {
    "01": "janvier", "02": "février",   "03": "mars",    "04": "avril",
    "05": "mai",     "06": "juin",      "07": "juillet", "08": "août",
    "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre",
}


# ══════════════════════════════════════════════════════════════════════════════
# SUPABASE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _sb_headers(extra: Optional[dict] = None) -> dict:
    h = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
    }
    if extra:
        h.update(extra)
    return h


def sb_get(path: str, params: str = "") -> list:
    url = f"{SUPABASE_URL}/rest/v1/{path}{'?' + params if params else ''}"
    r = requests.get(url, headers=_sb_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def sb_upsert(table: str, row: dict) -> bool:
    h = _sb_headers({"Prefer": "resolution=merge-duplicates,return=minimal"})
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, json=row, timeout=30)
    if r.status_code not in (200, 201, 204):
        print(f"  ⚠️  UPSERT {table}: HTTP {r.status_code} — {r.text[:200]}")
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
# NICHE CONFIG — chargement & gestion last_used
# ══════════════════════════════════════════════════════════════════════════════

def _load_niches() -> dict:
    if not NICHES_CFG.exists():
        print(f"❌  Config introuvable : {NICHES_CFG}")
        sys.exit(1)
    return json.loads(NICHES_CFG.read_text(encoding="utf-8"))


def _save_niches(data: dict) -> None:
    NICHES_CFG.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _days_since(niche: str, last_used: dict) -> float:
    val = last_used.get(niche)
    if not val or val == "null":
        return 999.0
    try:
        return max(0.0, (date.today() - datetime.fromisoformat(str(val)).date()).days)
    except (ValueError, TypeError):
        return 999.0


def _current_boosted(data: dict) -> list:
    month = datetime.now().month
    for rng, niches in data.get("seasonal_boost", {}).items():
        s, e = map(int, rng.split("-"))
        if (s <= e and s <= month <= e) or (s > e and (month >= s or month <= e)):
            return niches
    return []


# ══════════════════════════════════════════════════════════════════════════════
# PINTEREST TRENDS
# ══════════════════════════════════════════════════════════════════════════════

def fetch_pinterest_trends() -> dict:
    """
    Récupère les tendances Pinterest pour FR, US, GB, DE.
    Retourne un dict {keyword: {wow, mom, yoy, phase, score, region_count}}
    Fallback gracieux (dict vide) si token absent ou API hors-ligne.
    """
    if not PINTEREST_TOKEN:
        print("  ℹ️  PINTEREST_ACCESS_TOKEN absent — tendances ignorées (fallback saisonnier)")
        return {}

    headers = {
        "Authorization": f"Bearer {PINTEREST_TOKEN}",
        "Accept":        "application/json",
    }
    raw: dict = {}  # kw → {wow, mom, yoy, regions}

    for region in TREND_REGIONS:
        for tt in TREND_TYPES:
            url = f"{PINTEREST_BASE}/trends/keywords/{region}/top/{tt}"
            try:
                r = requests.get(
                    url, headers=headers,
                    params={"limit": 50, "include_demographics": "true"},
                    timeout=15,
                )
                if r.status_code != 200:
                    continue
                for item in r.json().get("trends", []):
                    kw = item.get("keyword", "").strip().lower()
                    if not kw:
                        continue

                    def _safe(v):
                        if v is None:
                            return None
                        f = float(v)
                        return None if f >= 10001 else f

                    entry = {
                        "wow":     _safe(item.get("pct_growth_wow")),
                        "mom":     _safe(item.get("pct_growth_mom")),
                        "yoy":     _safe(item.get("pct_growth_yoy")),
                        "regions": [region],
                    }
                    if kw not in raw:
                        raw[kw] = entry
                    else:
                        if region not in raw[kw]["regions"]:
                            raw[kw]["regions"].append(region)
                        # Merge: keep first non-None values
                        for metric in ("wow", "mom", "yoy"):
                            if raw[kw][metric] is None:
                                raw[kw][metric] = entry[metric]

            except Exception as e:
                print(f"  ⚠️  Trends {region}/{tt}: {e}")
                continue

    # Compute phase & score per keyword
    result = {}
    for kw, d in raw.items():
        w = d["wow"] or 0
        m = d["mom"] or 0
        if   w >= 30 and m < 120:  phase = "emerging"
        elif w >= 15 and m >= 80:  phase = "accelerating"
        elif w >= 5  and m >= 60:  phase = "peak"
        elif w < 0:                phase = "declining"
        else:                      phase = "stable"

        result[kw] = {
            **d,
            "phase":        phase,
            "score":        w + m * 0.3,
            "region_count": len(set(d["regions"])),
        }

    surfable = sum(1 for d in result.values() if d["phase"] in ("emerging", "accelerating", "peak"))
    print(f"  📈 {len(result)} tendances Pinterest — {surfable} en phase surfable")
    return result


def _trend_affinity(niche: str, niche_cfg: dict, trends: dict) -> float:
    """
    Score d'affinité entre une niche et les tendances Pinterest actuelles.
    Compare les trend_keywords de la niche avec les keywords tendance.
    """
    if not trends:
        return 0.0
    trend_kws = [kw.lower() for kw in niche_cfg.get("trend_keywords", [])]
    if not trend_kws:
        return 0.0
    total = 0.0
    for t_kw, td in trends.items():
        if td["phase"] in ("declining", "stable"):
            continue
        for nkw in trend_kws:
            if nkw in t_kw or t_kw in nkw or any(w in t_kw for w in nkw.split()):
                total += td["score"] * (1.0 + 0.2 * td["region_count"])
                break
    return total


# ══════════════════════════════════════════════════════════════════════════════
# NICHE SELECTION — score pondéré
# ══════════════════════════════════════════════════════════════════════════════

def pick_niche(data: dict, trends: dict, forced: Optional[str] = None) -> str:
    """
    Sélectionne la niche optimale.
    Score = days_since_last_use × base_weight × seasonal_boost × trend_affinity × jitter
    """
    import random

    if forced:
        niches = data.get("niches", [])
        if forced not in niches:
            print(f"  ⚠️  Niche '{forced}' inconnue dans la config — utilisée quand même")
        return forced

    niches        = data.get("niches", [])
    last_used     = data.get("last_used", {})
    boosted       = _current_boosted(data)
    niche_configs = data.get("_niche_config", {})

    scores = {}
    for n in niches:
        days        = _days_since(n, last_used)
        weight      = data.get("_weights", {}).get(n, 1.0)
        boost       = 2.0 if n in boosted else 1.0
        # Trend affinity clampé entre 1x et 6x
        trend_mult  = 1.0 + min(5.0, _trend_affinity(n, niche_configs.get(n, {}), trends) / 50.0)
        jitter      = random.uniform(0.8, 1.2)
        scores[n]   = days * weight * boost * trend_mult * jitter

    chosen = max(scores, key=scores.__getitem__)
    top5   = sorted(scores.items(), key=lambda x: -x[1])[:5]

    print(f"  📅 Mois {datetime.now().month}  |  Boostées: {boosted[:4]}")
    print(f"  🎯 Niche choisie : {chosen}")
    print(f"     Top 5 scores : { {k: round(v) for k, v in top5} }")
    return chosen


def mark_niche_used(niche: str, data: dict) -> dict:
    """Enregistre la date d'utilisation dans last_used."""
    data.setdefault("last_used", {})[niche] = datetime.now().isoformat()
    return data


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCT FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def _strip_accents(s: str) -> str:
    """Normalise NFD et supprime les diacritiques — ILIKE plus robuste avec noms anglais."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


_PRODUCT_SELECT = (
    "id,name,brand,image_url,rating,review_count,category_slug,"
    "affiliate_url,price,currency,merchant_key,description,llm_product_type"
)
_ORDER_QUALITY = "&order=rating.desc.nullslast,review_count.desc.nullslast,price.asc.nullslast"


def _pick_diverse(rows: list, count: int,
                  seen_ids: set = None, seen_types: set = None) -> list:
    """
    Sélectionne jusqu'à {count} produits en favorisant la diversité par llm_product_type.
    Modifie seen_ids et seen_types sur place pour permettre l'accumulation entre appels.
    """
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
            continue  # déjà un produit de ce type
        seen_ids.add(row["id"])
        if pt:
            seen_types.add(pt)
        products.append(row)
    return products


def fetch_diverse_products(niche: str, data: dict, trends: dict, count: int = 5) -> list:
    """
    Récupère {count} produits DIFFÉRENTS adaptés à la niche.

    Stratégie (par ordre de priorité) :
      1. LLM-tags  : llm_niches=cs.{niche}  (rapide, précis — nécessite classify-products.py)
      2. ILIKE     : fallback si llm_niches non rempli (search_queries + category_hints)
    """
    niche_cfg = data.get("_niche_config", {}).get(niche, {})

    # ── STRATÉGIE 1 : llm_niches (classification LLM) ────────────────────────
    seen_ids:   set = set()
    seen_types: set = set()
    products:   list = []

    params_llm = (
        f"llm_niches=cs.{{{niche}}}"
        f"{_ORDER_QUALITY}"
        f"&limit={count * 6}"
        "&active=not.is.false"
        f"&select={_PRODUCT_SELECT}"
    )
    try:
        rows = sb_get("products", params_llm)
        if rows:
            products = _pick_diverse(rows, count, seen_ids, seen_types)
    except Exception as e:
        print(f"  ⚠️  llm_niches query: {e}")

    # ── STRATÉGIE 2 : ILIKE (fallback si llm_niches vide) ────────────────────
    if not products:
        print(f"  ℹ️  llm_niches vide pour '{niche}' — fallback ILIKE (lancer classify-products.py)")
        products = _fetch_products_ilike(niche, niche_cfg, trends, count,
                                         seen_ids, seen_types)

    if not products:
        print(f"  ⚠️  Aucun produit trouvé pour '{niche}' — catalogue insuffisant")

    print(f"\n  📦 {len(products)} produits récupérés pour '{niche}' :")
    for i, p in enumerate(products[:count], 1):
        name  = (p.get("name") or "")[:55]
        brand = p.get("brand") or "?"
        price = p.get("price") or "?"
        cat   = p.get("llm_product_type") or p.get("category_slug") or ""
        print(f"     {i}. [{cat}] {brand} — {name} — {price} €")

    return products[:count]


def _fetch_products_ilike(niche: str, niche_cfg: dict, trends: dict, count: int,
                           seen_ids: set, seen_types: set) -> list:
    """
    Fallback ILIKE : utilisé tant que les produits ne sont pas classifiés par le LLM.
    Méthode slot-par-slot : AND multi-mots sur name, puis OR large, puis description.
    """
    base_queries   = list(niche_cfg.get("search_queries", [""]))
    category_hints = niche_cfg.get("category_hints", [])
    cat_prefix     = f"category_slug=in.({','.join(category_hints)})&" if category_hints else ""

    if trends:
        trend_kws_niche = [kw.lower() for kw in niche_cfg.get("trend_keywords", [])]
        trending_bonus  = [
            kw for kw, td in trends.items()
            if td["phase"] in ("emerging", "accelerating", "peak")
            and any(nkw in kw or kw in nkw for nkw in trend_kws_niche)
        ]
        if trending_bonus:
            base_queries = trending_bonus[:2] + base_queries

    queries  = (base_queries * 3)[:count * 2]
    products = []

    for query in queries:
        if len(products) >= count:
            break

        raw_words = re.sub(r"[^\w\s]", " ", query.lower()).split()
        words: list = []
        _seen_w: set = set()
        for w in raw_words:
            if len(w) < 3:
                continue
            for variant in (w, _strip_accents(w)):
                if variant not in _seen_w:
                    words.append(variant)
                    _seen_w.add(variant)
        if not words:
            continue

        rows = []
        # AND multi-mots
        if len(words) >= 2:
            and_parts = "&".join(f"name=ilike.*{w}*" for w in words[:3])
            try:
                rows = sb_get("products",
                              f"{cat_prefix}{and_parts}{_ORDER_QUALITY}"
                              f"&limit=30&active=not.is.false&select={_PRODUCT_SELECT}")
            except Exception as e:
                print(f"  ⚠️  [{query[:40]}] AND: {e}")
        # OR large si AND vide
        if not rows:
            or_parts = ",".join(f"name.ilike.*{w}*" for w in words[:5])
            try:
                rows = sb_get("products",
                              f"{cat_prefix}or=({or_parts}){_ORDER_QUALITY}"
                              f"&limit=30&active=not.is.false&select={_PRODUCT_SELECT}")
            except Exception as e:
                print(f"  ⚠️  [{query[:40]}] OR: {e}")
        # Description si toujours vide
        if not rows:
            d_parts = ",".join(f"description.ilike.*{w}*" for w in words[:3])
            try:
                rows = sb_get("products",
                              f"{cat_prefix}or=({d_parts})&order=rating.desc.nullslast"
                              f"&limit=30&active=not.is.false&select={_PRODUCT_SELECT}")
            except Exception as e:
                print(f"  ⚠️  [{query[:40]}] DESC: {e}")

        added = _pick_diverse(rows, 1, seen_ids, seen_types)
        products.extend(added)

    # Fallback catégorie limitée
    if len(products) < count and category_hints:
        cat_in = ",".join(category_hints)
        try:
            rows = sb_get("products",
                          f"category_slug=in.({cat_in})"
                          f"&order=rating.desc.nullslast"
                          f"&limit=200&active=not.is.false&select={_PRODUCT_SELECT}")
            extra = _pick_diverse(rows, count - len(products), seen_ids, seen_types)
            products.extend(extra)
        except Exception as e:
            print(f"  ⚠️  Fallback catégorie: {e}")

    return products[:count]


# ══════════════════════════════════════════════════════════════════════════════
# LLM — Ollama Cloud (minimax-m2.5:cloud)
# ══════════════════════════════════════════════════════════════════════════════

def _call_llm(prompt: str, max_tokens: int = 400) -> Optional[str]:
    """Appelle Ollama Cloud. Retourne None si clé absente ou échec."""
    if not OLLAMA_API_KEY:
        return None
    for attempt in range(3):
        try:
            r = requests.post(
                f"{OLLAMA_HOST}/api/chat",
                headers={
                    "Authorization": f"Bearer {OLLAMA_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":    OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream":   False,
                    "options":  {"temperature": 0.55, "num_predict": max_tokens},
                },
                timeout=90,
            )
            if r.status_code == 429:
                wait = 12 * (attempt + 1)
                print(f"  ⏳ Rate limit LLM — attente {wait}s…")
                time.sleep(wait)
                continue
            r.raise_for_status()
            text = r.json()["message"]["content"].strip()
            # Supprimer les caractères CJK que certains modèles injectent
            text = re.sub(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+", "", text).strip()
            return text
        except Exception as e:
            if attempt < 2:
                print(f"  ⏳ LLM tentative {attempt + 1}/3 : {e} — retry 8s…")
                time.sleep(8)
            else:
                print(f"  ⚠️  Ollama Cloud échec définitif : {e}")
    return None


def generate_content(niche: str, niche_label: str, month_fr: str, year: str,
                     products: list, data: dict) -> dict:
    """
    Génère : title_fr, intro_fr, blurbs[].
    Fallback template si LLM indisponible.
    """
    niche_cfg = data.get("_niche_config", {}).get(niche, {})
    template  = niche_cfg.get(
        "title_template",
        f"Top {len(products)} incontournables pour {{label}} en {{month}} {{year}}"
    )
    title = template.format(n=len(products), label=niche_label, month=month_fr, year=year)

    product_list = "\n".join(
        f"{i+1}. {p.get('name', '?')} ({p.get('brand', '?')}, {p.get('price', '?')} €)"
        for i, p in enumerate(products)
    )

    # ── Intro ─────────────────────────────────────────────────────────────────
    intro_prompt = (
        f"Tu rédiges une introduction courte (120-180 mots, ton naturel et enthousiaste, "
        f"style magazine) pour un article de blog intitulé :\n"
        f"« {title} »\n\n"
        f"Les {len(products)} produits présentés sont :\n{product_list}\n\n"
        f"Écris uniquement en français, mets en valeur la diversité des produits "
        f"et ce qu'ils apportent concrètement à {niche_label}. "
        f"Pas de titre, directement le corps de l'intro."
    )
    intro = _call_llm(intro_prompt, 380) or (
        f"Découvrez notre sélection de {len(products)} produits incontournables pour {niche_label} "
        f"en {month_fr} {year}. Des produits soigneusement choisis pour transformer "
        f"votre quotidien avec des solutions pratiques et tendance."
    )
    time.sleep(4)  # éviter back-to-back rate limit

    # ── Blurbs (1 appel groupé) ───────────────────────────────────────────────
    blurbs_prompt = (
        f"Génère une description courte (1 phrase, style factuel, avantage concret principal) "
        f"pour chacun de ces {len(products)} produits destinés à {niche_label}.\n"
        f"Réponds UNIQUEMENT en français avec {len(products)} lignes numérotées, sans texte avant ni après.\n"
        + "\n".join(f"{i+1}. ..." for i in range(len(products)))
        + f"\n\nProduits :\n{product_list}"
    )
    blurbs_raw = _call_llm(blurbs_prompt, 600)

    if blurbs_raw:
        parsed = re.findall(r"^\d+\.\s*(.+)", blurbs_raw, re.MULTILINE)
        if len(parsed) >= len(products):
            blurbs = [re.sub(r"\s+", " ", b).strip() for b in parsed[: len(products)]]
        else:
            blurbs = parsed + [
                f"{p.get('brand', '')} {p.get('name', '')} — idéal pour {niche_label}.".strip()
                for p in products[len(parsed):]
            ]
    else:
        blurbs = [
            f"{p.get('brand', '')} {p.get('name', '')} — idéal pour {niche_label}.".strip()
            for p in products
        ]

    return {"title": title, "intro": intro, "blurbs": blurbs}


# ══════════════════════════════════════════════════════════════════════════════
# PINTEREST IMAGE GENERATION — inspired by pinterest-affiliate-bot / generate_images.py
# ══════════════════════════════════════════════════════════════════════════════

def _load_font(size: int, bold: bool = False) -> "ImageFont.FreeTypeFont":
    """Charge une police adaptée, avec fallback système."""
    candidates = []
    if bold:
        candidates = [
            FONTS_DIR / "Poppins-Bold.ttf",
            FONTS_DIR / "Montserrat-Bold.ttf",
            FONTS_DIR / "BebasNeue-Regular.ttf",
            FONTS_DIR / "Anton-Regular.ttf",
            Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]
    else:
        candidates = [
            FONTS_DIR / "Montserrat-Medium.ttf",
            FONTS_DIR / "Poppins-Bold.ttf",
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
            Path("/System/Library/Fonts/Helvetica.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _wrap(text: str, font: "ImageFont.FreeTypeFont", max_w: int,
          draw: "ImageDraw.ImageDraw") -> list:
    """Découpe le texte en lignes pour tenir dans max_w pixels."""
    words = text.split()
    lines, cur = [], ""
    for word in words:
        test = f"{cur} {word}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _generate_bg_hf(prompt: str, dry_run: bool = False) -> Optional["Image.Image"]:
    """
    Génère un fond via HF FLUX.1-schnell.
    Retourne None si HF_TOKEN absent, dry_run=True, ou en cas d'échec.
    """
    if dry_run or not HF_TOKEN:
        return None

    NO_TEXT_PREFIX = (
        "PURE PHOTOGRAPH. ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, NO SIGNS, "
        "NO LOGOS, NO WATERMARKS ANYWHERE IN THE IMAGE. "
        "Professional interior lifestyle photography only. Scene: "
    )
    full_prompt = NO_TEXT_PREFIX + prompt.strip()
    url         = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers     = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload     = {"inputs": full_prompt, "parameters": {"width": PIN_W, "height": PIN_H}}

    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            if resp.status_code == 200:
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                return img.resize((PIN_W, PIN_H), Image.LANCZOS)
            elif resp.status_code == 503:
                wait = 20 * (attempt + 1)
                print(f"     HF modèle en chargement — attente {wait}s…")
                time.sleep(wait)
            elif resp.status_code == 429:
                print("     Rate limit HF — attente 60s…")
                time.sleep(60)
            else:
                print(f"     HF erreur {resp.status_code}: {resp.text[:120]}")
                break
        except Exception as e:
            print(f"     HF réseau: {e}")
            time.sleep(10)
    return None


def _gradient_bg(top_color: tuple = (14, 20, 36), bot_color: tuple = (22, 32, 56)) -> "Image.Image":
    """Fond dégradé sombre — fallback quand HF n'est pas disponible."""
    img  = Image.new("RGB", (PIN_W, PIN_H))
    draw = ImageDraw.Draw(img)
    r0, g0, b0 = top_color
    r1, g1, b1 = bot_color
    for y in range(PIN_H):
        t = y / PIN_H
        draw.line([(0, y), (PIN_W, y)], fill=(
            int(r0 + (r1 - r0) * t),
            int(g0 + (g1 - g0) * t),
            int(b0 + (b1 - b0) * t),
        ))
    return img


def _draw_watermark(draw: "ImageDraw.ImageDraw") -> None:
    """Watermark discret en bas à droite."""
    font  = _load_font(19)
    label = SITE_URL.replace("https://", "")
    w     = draw.textbbox((0, 0), label, font=font)[2]
    draw.text((PIN_W - w - 28, PIN_H - 38), label, font=font, fill=(130, 155, 185))


# ── Visuel 1 — Hero ───────────────────────────────────────────────────────────

def make_hero_pin(
    title: str,
    niche_label: str,
    month_fr: str,
    year: str,
    image_style: str,
    save_to: Path,
    dry_run: bool = False,
) -> str:
    """
    Visuel principal : scène d'ambiance niche + titre de l'article.
    Layout : photo HF plein format + overlay sombre en bas (420px).
    """
    print(f"  🖼️  Visuel 1 — Hero…")
    bg     = _generate_bg_hf(image_style, dry_run) or _gradient_bg((14, 20, 38), (20, 35, 60))
    canvas = bg.copy()
    draw   = ImageDraw.Draw(canvas)

    ACCENT = (16, 185, 129)   # emerald-500
    WHITE  = (255, 255, 255)
    LGRAY  = (200, 220, 240)

    ov_h   = 430
    ov_y   = PIN_H - ov_h
    pad    = 52

    # Légère zone floutée derrière l'overlay
    blur_zone = bg.crop((0, ov_y - 30, PIN_W, PIN_H))
    blur_zone = blur_zone.filter(ImageFilter.GaussianBlur(radius=6))
    canvas.paste(blur_zone, (0, ov_y - 30))

    # Overlay sombre semi-transparent
    overlay = Image.new("RGBA", (PIN_W, ov_h), (12, 18, 32, 218))
    canvas.paste(Image.new("RGB", (PIN_W, ov_h), (12, 18, 32)), (0, ov_y),
                 overlay.split()[3])

    y = ov_y + 36

    # Badge mois
    bf    = _load_font(21, bold=True)
    badge = f"✦  TOP 5  ·  {month_fr.upper()} {year}"
    bb    = draw.textbbox((0, 0), badge, font=bf)
    bw, bh = bb[2] + 26, bb[3] + 14
    draw.rounded_rectangle([pad, y, pad + bw, y + bh], radius=6, fill=ACCENT)
    draw.text((pad + 13, y + 7), badge, font=bf, fill=WHITE)
    y += bh + 24

    # Titre
    tf     = _load_font(50, bold=True)
    for line in _wrap(title, tf, PIN_W - 2 * pad, draw)[:3]:
        lh = draw.textbbox((0, 0), line, font=tf)[3]
        # Ombre
        draw.text((pad + 2, y + 2), line, font=tf, fill=(0, 0, 0))
        draw.text((pad, y), line, font=tf, fill=WHITE)
        y += lh + 8
    y += 12

    # Sous-titre
    sf  = _load_font(27)
    sub = f"5 produits soigneusement sélectionnés pour {niche_label}"
    for line in _wrap(sub, sf, PIN_W - 2 * pad, draw)[:2]:
        draw.text((pad, y), line, font=sf, fill=LGRAY)
        y += draw.textbbox((0, 0), line, font=sf)[3] + 5

    # Indicateur d'URL
    url_f = _load_font(22)
    slug_hint = f"→  {SITE_URL.replace('https://', '')}/lifestyle"
    draw.text((pad, PIN_H - 56), slug_hint, font=url_f, fill=(100, 150, 190))

    _draw_watermark(draw)
    canvas.save(str(save_to), "JPEG", quality=90)
    print(f"     → {save_to.name}")
    return str(save_to)


# ── Visuel 2 — Spotlight ──────────────────────────────────────────────────────

def make_spotlight_pin(
    product: dict,
    title: str,
    niche_label: str,
    month_fr: str,
    year: str,
    image_style: str,
    save_to: Path,
    dry_run: bool = False,
) -> str:
    """
    Visuel produit #1 : focus avec prix, marque, et contexte article.
    """
    print(f"  🖼️  Visuel 2 — Spotlight…")
    # Variante plus warm pour distinguer du hero
    style_warm = image_style + ", warm afternoon light, cinematic"
    bg     = _generate_bg_hf(style_warm, dry_run) or _gradient_bg((28, 22, 48), (18, 14, 38))
    canvas = bg.copy()
    draw   = ImageDraw.Draw(canvas)

    ACCENT = (16, 185, 129)
    WHITE  = (255, 255, 255)
    LGRAY  = (190, 210, 230)
    pad    = 52

    # Dégradé overlay en haut (pour le texte top)
    for y_row in range(260):
        alpha = int(200 * (1 - y_row / 260))
        draw.line([(0, y_row), (PIN_W, y_row)],
                  fill=(12, 16, 28))

    # Dégradé overlay en bas (panel prix)
    ov_h = 420
    ov_y = PIN_H - ov_h
    overlay = Image.new("RGBA", (PIN_W, ov_h), (10, 14, 26, 225))
    canvas.paste(Image.new("RGB", (PIN_W, ov_h), (10, 14, 26)), (0, ov_y),
                 overlay.split()[3])

    # Haut : label niche
    top_f = _load_font(27)
    draw.text((pad, 30), f"Pour {niche_label}  ·  {month_fr} {year}", font=top_f,
              fill=(160, 220, 200))

    # Marque
    brand = (product.get("brand") or "").strip()
    if brand:
        bf = _load_font(28)
        draw.text((pad, 72), brand.upper(), font=bf, fill=ACCENT)

    # Nom produit (grand, top de l'image)
    name_f = _load_font(50, bold=True)
    name   = (product.get("name") or "")[:70]
    y_n    = 110
    for line in _wrap(name, name_f, PIN_W - 2 * pad, draw)[:2]:
        lh = draw.textbbox((0, 0), line, font=name_f)[3]
        draw.text((pad + 2, y_n + 2), line, font=name_f, fill=(0, 0, 0))
        draw.text((pad, y_n), line, font=name_f, fill=WHITE)
        y_n += lh + 8

    # Panel bas : prix + contexte
    y = ov_y + 32

    price = product.get("price")
    if price:
        pl_f = _load_font(23)
        draw.text((pad, y), "À partir de", font=pl_f, fill=(150, 200, 185))
        y += 27
        pv_f  = _load_font(58, bold=True)
        price_txt = f"{price} €"
        draw.text((pad, y), price_txt, font=pv_f, fill=ACCENT)
        y += draw.textbbox((0, 0), price_txt, font=pv_f)[3] + 18

    # Référence à l'article
    ctx_f = _load_font(27)
    ctx   = f"Inclus dans : « {title[:55]} »"
    for line in _wrap(ctx, ctx_f, PIN_W - 2 * pad, draw)[:2]:
        draw.text((pad, y), line, font=ctx_f, fill=LGRAY)
        y += draw.textbbox((0, 0), line, font=ctx_f)[3] + 5

    _draw_watermark(draw)
    canvas.save(str(save_to), "JPEG", quality=90)
    print(f"     → {save_to.name}")
    return str(save_to)


# ── Visuel 3 — Checklist ──────────────────────────────────────────────────────

def make_checklist_pin(
    products: list,
    title: str,
    niche_label: str,
    month_fr: str,
    year: str,
    save_to: Path,
) -> str:
    """
    Liste des 5 produits sur fond sombre — aucun appel HF, 100% Pillow.
    Adapté du style generate_images.py (pinterest-affiliate-bot).
    """
    print(f"  🖼️  Visuel 3 — Checklist (no HF)…")
    canvas = _gradient_bg((10, 15, 28), (18, 26, 46))
    draw   = ImageDraw.Draw(canvas)

    ACCENT = (16, 185, 129)
    WHITE  = (255, 255, 255)
    LGRAY  = (195, 215, 235)
    DGRAY  = (40, 58, 80)
    pad    = 58

    # Texture légère (grille subtile)
    for x in range(0, PIN_W, 44):
        draw.line([(x, 0), (x, PIN_H)], fill=(255, 255, 255, 5))
    for y_g in range(0, PIN_H, 44):
        draw.line([(0, y_g), (PIN_W, y_g)], fill=(255, 255, 255, 5))

    y = 72

    # Badge centré
    bf    = _load_font(22, bold=True)
    badge = f"✦  TOP 5  ·  {month_fr.upper()} {year}"
    bb    = draw.textbbox((0, 0), badge, font=bf)
    bw, bh = bb[2] + 28, bb[3] + 14
    bx    = (PIN_W - bw) // 2
    draw.rounded_rectangle([bx, y, bx + bw, y + bh], radius=6, fill=ACCENT)
    draw.text((bx + 14, y + 7), badge, font=bf, fill=WHITE)
    y += bh + 30

    # Titre centré (multi-ligne)
    tf  = _load_font(46, bold=True)
    for line in _wrap(title, tf, PIN_W - 2 * pad, draw)[:3]:
        lw = draw.textbbox((0, 0), line, font=tf)[2]
        lh = draw.textbbox((0, 0), line, font=tf)[3]
        draw.text(((PIN_W - lw) // 2, y), line, font=tf, fill=WHITE)
        y += lh + 6
    y += 26

    # Séparateur
    draw.line([(pad, y), (PIN_W - pad, y)], fill=ACCENT, width=2)
    y += 28

    # Liste des produits
    num_f  = _load_font(38, bold=True)
    name_f = _load_font(30)
    brd_f  = _load_font(21)
    prc_f  = _load_font(26, bold=True)

    for i, p in enumerate(products[:5]):
        row_start = y

        # Numéro dans un cercle
        circle_r = 28
        cx, cy   = pad + circle_r, y + circle_r
        draw.ellipse([(cx - circle_r, cy - circle_r), (cx + circle_r, cy + circle_r)],
                     fill=ACCENT)
        num_txt = str(i + 1)
        nb      = draw.textbbox((0, 0), num_txt, font=num_f)
        draw.text(
            (cx - (nb[2] - nb[0]) // 2, cy - (nb[3] - nb[1]) // 2),
            num_txt, font=num_f, fill=WHITE,
        )

        # Contenu à droite du cercle
        tx = pad + 2 * circle_r + 18
        ty = y

        brand = (p.get("brand") or "").strip()
        name  = (p.get("name") or "").strip()
        price = p.get("price")

        if brand:
            draw.text((tx, ty), brand, font=brd_f, fill=ACCENT)
            ty += 24

        # Nom produit (max 2 lignes)
        for line in _wrap(name, name_f, PIN_W - tx - pad, draw)[:2]:
            draw.text((tx, ty), line, font=name_f, fill=LGRAY)
            ty += draw.textbbox((0, 0), line, font=name_f)[3] + 2

        if price:
            draw.text((tx, ty), f"{price} €", font=prc_f, fill=ACCENT)
            ty += 30

        # Ligne séparatrice légère
        item_bottom = max(y + 2 * circle_r, ty) + 14
        draw.line([(pad + 2 * circle_r + 10, item_bottom),
                   (PIN_W - pad, item_bottom)], fill=DGRAY, width=1)

        y = item_bottom + 16

    y += 10

    # CTA bas
    cta_f = _load_font(24)
    cta   = f"Voir l'article complet → {SITE_URL.replace('https://', '')}"
    cta_w = draw.textbbox((0, 0), cta, font=cta_f)[2]
    draw.text(((PIN_W - cta_w) // 2, PIN_H - 68), cta, font=cta_f, fill=(95, 145, 195))

    _draw_watermark(draw)
    canvas.save(str(save_to), "JPEG", quality=92)
    print(f"     → {save_to.name}")
    return str(save_to)


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION — génération des N pins Pinterest
# ══════════════════════════════════════════════════════════════════════════════

def generate_pins(
    article_slug: str,
    title: str,
    niche: str,
    niche_label: str,
    month_fr: str,
    year: str,
    products: list,
    data: dict,
    pins_count: int = 3,
    dry_run: bool = False,
) -> list:
    """Génère jusqu'à pins_count visuels Pinterest. Retourne les chemins locaux."""
    niche_cfg   = data.get("_niche_config", {}).get(niche, {})
    image_style = niche_cfg.get(
        "image_style",
        f"Modern interior design for {niche_label}, cozy lifestyle photography, no text",
    )

    slug_safe = re.sub(r"[^a-z0-9-]", "", article_slug.lower())[:42]
    paths     = []

    variants = [
        ("hero",      lambda: make_hero_pin(
            title, niche_label, month_fr, year, image_style,
            OUTPUT_DIR / f"{slug_safe}_hero.jpg", dry_run,
        )),
        ("spotlight", lambda: make_spotlight_pin(
            products[0], title, niche_label, month_fr, year, image_style,
            OUTPUT_DIR / f"{slug_safe}_spotlight.jpg", dry_run,
        )),
        ("checklist", lambda: make_checklist_pin(
            products, title, niche_label, month_fr, year,
            OUTPUT_DIR / f"{slug_safe}_checklist.jpg",
        )),
    ]

    for variant, fn in variants[:pins_count]:
        try:
            path = fn()
            paths.append(path)
        except Exception as e:
            print(f"  ⚠️  Visuel '{variant}' échoué : {e}")

    return paths


# ══════════════════════════════════════════════════════════════════════════════
# ARTICLE STORAGE
# ══════════════════════════════════════════════════════════════════════════════

def save_article(
    niche: str,
    niche_label: str,
    month: str,
    content: dict,
    products: list,
    pin_paths: list,
    trending_kws: list,
    dry_run: bool,
) -> str:
    """Upsert dans lifestyle_articles. Retourne le slug."""
    year, mo = month.split("-")
    slug     = f"{niche.replace('_', '-')}-{month}"

    enriched = [
        {
            "id":        p["id"],
            "name":      p.get("name", ""),
            "brand":     p.get("brand"),
            "price":     p.get("price"),
            "url":       p.get("affiliate_url") or "",
            "image_url": p.get("image_url"),
            "rating":    p.get("rating"),
            "category":  p.get("category_slug"),
            "blurb_fr":  content["blurbs"][i] if i < len(content["blurbs"]) else "",
        }
        for i, p in enumerate(products)
    ]

    row = {
        "slug":              slug,
        "niche":             niche,
        "niche_label_fr":    niche_label,
        "title_fr":          content["title"],
        "intro_fr":          content["intro"],
        "products":          json.dumps(enriched, ensure_ascii=False),
        "trending_keywords": json.dumps(trending_kws[:20], ensure_ascii=False),
        "month":             month,
        "pin_images":        json.dumps(pin_paths, ensure_ascii=False),
        "is_published":      True,
        "generated_at":      datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        print(f"\n  ┌─ [DRY-RUN] Slug   : {slug}")
        print(f"  │  Titre            : {content['title']}")
        print(f"  │  Intro            : {content['intro'][:120]}…")
        for p in enriched:
            print(f"  │  #{enriched.index(p)+1}  {p['name'][:55]} — {p.get('price','?')} €")
            print(f"  │     ↳ {p.get('blurb_fr','')[:95]}")
        print(f"  └─ Images: {[Path(p).name for p in pin_paths]}")
        return slug

    ok = sb_upsert("lifestyle_articles", row)
    if ok:
        print(f"  ✅  Sauvegardé : {slug}")
    return slug


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Génère un article lifestyle Top-5 avec visuels Pinterest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode", choices=["top5-lifestyle", "top5-product"],
        default="top5-lifestyle",
        help="Type d'article (défaut: top5-lifestyle)",
    )
    parser.add_argument(
        "--niche", default=None,
        help="Forcer une niche (ex: smart_home, gaming_setup). Auto si absent.",
    )
    parser.add_argument(
        "--month", default=datetime.now().strftime("%Y-%m"),
        help="Mois cible YYYY-MM (défaut: mois courant)",
    )
    parser.add_argument(
        "--pins-count", type=int, default=3, metavar="N",
        help="Nombre de visuels Pinterest à générer (défaut: 3, max: 3)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simule sans écrire en base (images quand même générées sauf --no-images)",
    )
    parser.add_argument(
        "--no-images", action="store_true",
        help="Ne génère pas les visuels Pinterest (plus rapide)",
    )
    args = parser.parse_args()

    # ── Délégation mode produit comparatif ──────────────────────────────────
    if args.mode == "top5-product":
        print("Mode top5-product → délégation à scripts/generate-top5.py")
        import subprocess
        cmd = [sys.executable, str(ROOT / "scripts" / "generate-top5.py"), "--month", args.month]
        if args.dry_run:
            cmd.append("--dry-run")
        subprocess.run(cmd, check=False)
        return

    # ── Info run ─────────────────────────────────────────────────────────────
    year, mo = args.month.split("-")
    month_fr  = MONTH_FR.get(mo, mo)
    llm_info  = f"Ollama ({OLLAMA_MODEL})" if OLLAMA_API_KEY else "template fallback"
    hf_info   = "HF FLUX.1-schnell" if (HF_TOKEN and not args.no_images) else "gradient fallback"

    print(f"\n{'═'*58}")
    print(f"  🏠  Lifestyle Article Generator — {month_fr} {year}")
    print(f"  LLM : {llm_info}")
    print(f"  IMG : {hf_info}  ({args.pins_count} visuels)")
    if args.dry_run:
        print("  Mode DRY-RUN (pas d'écriture Supabase)")
    if args.no_images:
        print("  Mode NO-IMAGES")
    print(f"{'═'*58}\n")

    # ── 1. Chargement config niche ────────────────────────────────────────────
    data = _load_niches()

    # ── 2. Tendances Pinterest ────────────────────────────────────────────────
    print("📈 Récupération des tendances Pinterest…")
    trends = fetch_pinterest_trends()

    # ── 3. Sélection de niche ─────────────────────────────────────────────────
    print("\n🎯 Sélection de la niche…")
    niche       = pick_niche(data, trends, forced=args.niche)
    niche_cfg   = data.get("_niche_config", {}).get(niche, {})
    niche_label = niche_cfg.get("label_fr", niche.replace("_", " "))

    # ── 4. Marquer la niche utilisée ─────────────────────────────────────────
    if not args.dry_run:
        data = mark_niche_used(niche, data)
        _save_niches(data)
        print(f"  📝 Niche '{niche}' marquée comme utilisée")

    # ── 5. Récupération des produits ─────────────────────────────────────────
    print(f"\n🛒 Recherche de produits diversifiés pour «{niche_label}»…")
    products = fetch_diverse_products(niche, data, trends, count=5)
    if not products:
        print("❌  Aucun produit trouvé — abandon")
        sys.exit(1)

    # ── 6. Génération contenu LLM ─────────────────────────────────────────────
    print(f"\n✍️  Génération du contenu ({llm_info})…")
    content = generate_content(niche, niche_label, month_fr, year, products, data)
    print(f"  Titre : {content['title']}")

    # Extraire les keywords tendance pour les stocker
    trending_kws = [kw for kw, td in trends.items()
                    if td.get("phase") in ("emerging", "accelerating", "peak")][:20]

    # ── 7. Génération des visuels Pinterest ──────────────────────────────────
    pin_paths = []
    if not args.no_images:
        count = max(1, min(args.pins_count, 3))
        print(f"\n🎨 Génération de {count} visuel(s) Pinterest…")
        slug_for_path = f"{niche.replace('_', '-')}-{args.month}"
        pin_paths = generate_pins(
            slug_for_path, content["title"],
            niche, niche_label,
            month_fr, year,
            products, data,
            pins_count=count,
            dry_run=args.dry_run,
        )

    # ── 8. Sauvegarde Supabase ────────────────────────────────────────────────
    print(f"\n💾 Sauvegarde{'  [DRY-RUN]' if args.dry_run else ''}…")
    slug = save_article(
        niche, niche_label, args.month,
        content, products, pin_paths, trending_kws,
        args.dry_run,
    )

    # Mise à jour des images si générées après le premier upsert
    if pin_paths and not args.dry_run:
        sb_upsert("lifestyle_articles", {
            "slug":       slug,
            "pin_images": json.dumps(pin_paths, ensure_ascii=False),
        })

    # ── 9. Résumé final ───────────────────────────────────────────────────────
    article_url = f"{SITE_URL}/lifestyle/{slug}"
    print(f"\n{'─'*58}")
    print(f"  ✅  Article : {slug}")
    print(f"  📌  Titre   : {content['title']}")
    print(f"  🛒  Produits: {len(products)}")
    print(f"  🖼️   Images  : {len(pin_paths)}")
    for p in pin_paths:
        print(f"       · {Path(p).name}")
    print(f"  🌐  URL     : {article_url}")
    if pin_paths:
        print(f"\n  ℹ️   Pour publier sur Pinterest après mise en production :")
        print(f"       python3 scripts/publish-pinterest.py --lifestyle-slug {slug}")
    print(f"{'─'*58}\n")


if __name__ == "__main__":
    main()
