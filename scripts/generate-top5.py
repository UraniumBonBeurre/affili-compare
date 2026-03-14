#!/usr/bin/env python3
"""
generate-top5.py — Articles "Top 5" par rotation de niche
==========================================================

PIPELINE :
  1.  Charge config/lifestyle_niches.json (niches, poids, boosts saisonniers, last_used)
  2.  Récupère les tendances Pinterest FR/US/GB/DE (gracieux si PINTEREST_ACCESS_TOKEN absent)
  3.  Sélectionne la niche optimale :
        score = days_since_last_use × base_weight × seasonal_boost × trend_affinity × jitter
  4.  Récupère 5 produits DIVERSIFIÉS :
        - Priorité : llm_niches=cs.{niche}  (colonnes classifiées par Gemini)
        - Fallback : ILIKE sur search_queries de la niche
  5.  Génère titre + intro + blurbs individuels via Ollama Cloud (minimax-m2.5:cloud)
        Fallback template si OLLAMA_CLOUD_API_KEY absent
  6.  Upsert dans la table top5_articles de Supabase
  7.  Met à jour last_used dans lifestyle_niches.json (anti-répétition)

USAGE :
    python3 scripts/generate-top5.py               # 1 article, niche automatique
    python3 scripts/generate-top5.py --count 3     # 3 articles, niches différentes
    python3 scripts/generate-top5.py --niche gaming_setup   # Forcer une niche
    python3 scripts/generate-top5.py --dry-run     # Affiche sans enregistrer
    python3 scripts/generate-top5.py --month 2026-04

VARIABLES D'ENV (.env.local) :
    NEXT_PUBLIC_SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
    OLLAMA_CLOUD_API_KEY        (requis LLM, sinon → template)
    PINTEREST_ACCESS_TOKEN      (optionnel — tendances)
    PINTEREST_API_BASE          (défaut: https://api.pinterest.com/v5)
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("❌  pip install requests")
    sys.exit(1)

# ── Chargement .env.local ─────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
for _env in (ROOT / ".env.local", ROOT / ".env"):
    if _env.exists():
        for _line in _env.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                k, _, v = _line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL    = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY    = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
OLLAMA_API_KEY  = os.environ.get("OLLAMA_CLOUD_API_KEY", "")
OLLAMA_HOST     = "https://api.ollama.com"
OLLAMA_MODEL    = "deepseek-v3.2:cloud"
PINTEREST_TOKEN = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
PINTEREST_BASE  = os.environ.get("PINTEREST_API_BASE", "https://api.pinterest.com/v5").rstrip("/")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌  NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY requis dans .env.local")
    sys.exit(1)

# ── Constantes ────────────────────────────────────────────────────────────────
NICHES_CFG = ROOT / "config" / "lifestyle_niches.json"

TREND_REGIONS = ["FR", "US", "GB", "DE"]
TREND_TYPES   = ["growing", "monthly", "yearly"]

MONTH_FR = {
    "01": "janvier", "02": "février",   "03": "mars",    "04": "avril",
    "05": "mai",     "06": "juin",      "07": "juillet", "08": "août",
    "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre",
}

_PRODUCT_SELECT = (
    "id,name,brand,image_url,rating,review_count,category_slug,"
    "affiliate_url,price,currency,merchant_key,description,llm_product_type"
)
_ORDER_QUALITY = "&order=rating.desc.nullslast,review_count.desc.nullslast,price.asc.nullslast"


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
    Récupère les tendances Pinterest FR/US/GB/DE.
    Retourne un dict {keyword: {wow, mom, yoy, phase, score, region_count}}.
    Fallback gracieux (dict vide) si token absent ou API hors-ligne.
    """
    if not PINTEREST_TOKEN:
        print("  ℹ️  PINTEREST_ACCESS_TOKEN absent — tendances ignorées (fallback saisonnier)")
        return {}

    headers = {"Authorization": f"Bearer {PINTEREST_TOKEN}", "Accept": "application/json"}
    raw: dict = {}

    for region in TREND_REGIONS:
        for tt in TREND_TYPES:
            url = f"{PINTEREST_BASE}/trends/keywords/{region}/top/{tt}"
            try:
                r = requests.get(url, headers=headers,
                                  params={"limit": 50, "include_demographics": "true"},
                                  timeout=15)
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
                        for metric in ("wow", "mom", "yoy"):
                            if raw[kw][metric] is None:
                                raw[kw][metric] = entry[metric]
            except Exception as e:
                print(f"  ⚠️  Trends {region}/{tt}: {e}")

    result = {}
    for kw, d in raw.items():
        w = d["wow"] or 0
        m = d["mom"] or 0
        if   w >= 30 and m < 120:  phase = "emerging"
        elif w >= 15 and m >= 80:  phase = "accelerating"
        elif w >= 5  and m >= 60:  phase = "peak"
        elif w < 0:                phase = "declining"
        else:                      phase = "stable"
        result[kw] = {**d, "phase": phase, "score": w + m * 0.3,
                      "region_count": len(set(d["regions"]))}

    surfable = sum(1 for d in result.values() if d["phase"] in ("emerging", "accelerating", "peak"))
    print(f"  📈 {len(result)} tendances Pinterest — {surfable} en phase surfable")
    return result


def _trend_affinity(niche: str, niche_cfg: dict, trends: dict) -> float:
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
# NICHE SELECTION
# ══════════════════════════════════════════════════════════════════════════════

def pick_niche(data: dict, trends: dict, forced: Optional[str] = None,
               exclude: Optional[set] = None) -> str:
    """
    Sélectionne la niche optimale (non présente dans `exclude`).
    Score = days_since_last_use × base_weight × seasonal_boost × trend_affinity × jitter
    """
    import random

    if forced:
        if forced not in data.get("niches", []):
            print(f"  ⚠️  Niche '{forced}' inconnue dans la config — utilisée quand même")
        return forced

    niches        = [n for n in data.get("niches", []) if n not in (exclude or set())]
    last_used     = data.get("last_used", {})
    boosted       = _current_boosted(data)
    niche_configs = data.get("_niche_config", {})

    scores = {}
    for n in niches:
        days       = _days_since(n, last_used)
        weight     = data.get("_weights", {}).get(n, 1.0)
        boost      = 2.0 if n in boosted else 1.0
        trend_mult = 1.0 + min(5.0, _trend_affinity(n, niche_configs.get(n, {}), trends) / 50.0)
        jitter     = random.uniform(0.8, 1.2)
        scores[n]  = days * weight * boost * trend_mult * jitter

    chosen = max(scores, key=scores.__getitem__)
    top5   = sorted(scores.items(), key=lambda x: -x[1])[:5]
    print(f"  📅 Mois {datetime.now().month}  |  Boostées: {boosted[:4]}")
    print(f"  🎯 Niche choisie : {chosen}")
    print(f"     Top 5 scores : { {k: round(v) for k, v in top5} }")
    return chosen


def mark_niche_used(niche: str, data: dict) -> dict:
    data.setdefault("last_used", {})[niche] = datetime.now().isoformat()
    return data


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCT FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _pick_diverse(rows: list, count: int,
                  seen_ids: set = None, seen_types: set = None) -> list:
    """Sélectionne jusqu'à {count} produits en favorisant la diversité par llm_product_type."""
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


def fetch_diverse_products(niche: str, data: dict, trends: dict, count: int = 5) -> list:
    """
    Récupère {count} produits DIVERSIFIÉS adaptés à la niche.
    Stratégie 1 : llm_niches=cs.{niche}  (colonnes Gemini)
    Stratégie 2 : ILIKE fallback (search_queries + category_hints)
    """
    niche_cfg = data.get("_niche_config", {}).get(niche, {})
    seen_ids:   set = set()
    seen_types: set = set()
    products:   list = []

    # ── Stratégie 1 : LLM tags ────────────────────────────────────────────────
    try:
        rows = sb_get("products",
                      f"llm_niches=cs.{{{niche}}}"
                      f"{_ORDER_QUALITY}"
                      f"&limit={count * 6}"
                      "&active=not.is.false"
                      f"&select={_PRODUCT_SELECT}")
        if rows:
            products = _pick_diverse(rows, count, seen_ids, seen_types)
    except Exception as e:
        print(f"  ⚠️  llm_niches query: {e}")

    # ── Stratégie 2 : ILIKE fallback ─────────────────────────────────────────
    if not products:
        print(f"  ℹ️  llm_niches vide pour '{niche}' — fallback ILIKE")
        products = _fetch_products_ilike(niche, niche_cfg, trends, count,
                                          seen_ids, seen_types)

    if not products:
        print(f"  ⚠️  Aucun produit trouvé pour '{niche}'")

    print(f"\n  📦 {len(products)} produits pour '{niche}' :")
    for i, p in enumerate(products[:count], 1):
        cat  = p.get("llm_product_type") or p.get("category_slug") or ""
        name = (p.get("name") or "")[:55]
        print(f"     {i}. [{cat}] {p.get('brand','?')} — {name} — {p.get('price','?')} €")

    return products[:count]


def _fetch_products_ilike(niche: str, niche_cfg: dict, trends: dict, count: int,
                           seen_ids: set, seen_types: set) -> list:
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
        if len(words) >= 2:
            and_parts = "&".join(f"name=ilike.*{w}*" for w in words[:3])
            try:
                rows = sb_get("products",
                              f"{cat_prefix}{and_parts}{_ORDER_QUALITY}"
                              f"&limit=30&active=not.is.false&select={_PRODUCT_SELECT}")
            except Exception as e:
                print(f"  ⚠️  ILIKE AND [{query[:40]}]: {e}")
        if not rows:
            or_parts = ",".join(f"name.ilike.*{w}*" for w in words[:5])
            try:
                rows = sb_get("products",
                              f"{cat_prefix}or=({or_parts}){_ORDER_QUALITY}"
                              f"&limit=30&active=not.is.false&select={_PRODUCT_SELECT}")
            except Exception as e:
                print(f"  ⚠️  ILIKE OR [{query[:40]}]: {e}")

        added = _pick_diverse(rows, 1, seen_ids, seen_types)
        products.extend(added)

    # Fallback catégorie large
    if len(products) < count and category_hints:
        cat_in = ",".join(category_hints)
        try:
            rows = sb_get("products",
                          f"category_slug=in.({cat_in})"
                          f"&order=rating.desc.nullslast&limit=200"
                          f"&active=not.is.false&select={_PRODUCT_SELECT}")
            products.extend(_pick_diverse(rows, count - len(products), seen_ids, seen_types))
        except Exception as e:
            print(f"  ⚠️  Fallback catégorie: {e}")

    return products[:count]


# ══════════════════════════════════════════════════════════════════════════════
# OLLAMA CLOUD LLM
# ══════════════════════════════════════════════════════════════════════════════

def _call_llm(prompt: str, max_tokens: int = 300) -> Optional[str]:
    if not OLLAMA_API_KEY:
        return None
    for attempt in range(3):
        try:
            r = requests.post(
                f"{OLLAMA_HOST}/api/chat",
                headers={"Authorization": f"Bearer {OLLAMA_API_KEY}",
                         "Content-Type":  "application/json"},
                json={"model":    OLLAMA_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "stream":   False,
                      "options":  {"temperature": 0.5, "num_predict": max_tokens}},
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


def _generate_content(niche: str, niche_label: str, month_fr: str, year: str,
                      products: list, data: dict) -> dict:
    """Génère title_fr, intro_fr et blurbs[] via LLM (fallback template)."""
    niche_cfg = data.get("_niche_config", {}).get(niche, {})
    template  = niche_cfg.get(
        "title_template",
        f"Top {len(products)} incontournables pour {{label}} en {{month}} {{year}}"
    )
    title = template.format(n=len(products), label=niche_label, month=month_fr, year=year)

    product_list = "\n".join(
        f"{i+1}. {p.get('name','?')} ({p.get('brand','?')}, {p.get('price','?')} €)"
        for i, p in enumerate(products)
    )

    # Intro
    intro_fallback = (
        f"Découvrez notre sélection de {len(products)} produits incontournables pour "
        f"{niche_label} en {month_fr} {year}. Des produits soigneusement choisis pour "
        f"transformer votre quotidien avec des solutions pratiques et tendance."
    )
    intro_prompt = (
        f"Tu rédiges une introduction courte (120-180 mots, ton naturel et enthousiaste, "
        f"style magazine) pour un article de blog intitulé :\n"
        f"« {title} »\n\n"
        f"Les {len(products)} produits présentés sont :\n{product_list}\n\n"
        f"Écris uniquement en français, mets en valeur la diversité des produits "
        f"et ce qu'ils apportent concrètement à {niche_label}. "
        f"Pas de titre, directement le corps de l'intro."
    )
    intro = _call_llm(intro_prompt, 380) or intro_fallback
    time.sleep(4)

    # Blurbs (1 appel groupé)
    blurbs_prompt = (
        f"Génère une description courte (1 phrase, style factuel, avantage concret principal) "
        f"pour chacun de ces {len(products)} produits destinés à {niche_label}.\n"
        f"Réponds UNIQUEMENT en français avec {len(products)} lignes numérotées, sans texte avant ni après.\n"
        + "\n".join(f"{i+1}. ..." for i in range(len(products)))
        + f"\n\nProduits :\n{product_list}"
    )
    blurbs_raw = _call_llm(blurbs_prompt, 600)

    fallback_blurbs = [
        f"{p.get('brand','')} {p.get('name','')} — idéal pour {niche_label}.".strip()
        for p in products
    ]
    if blurbs_raw:
        parsed = re.findall(r"^\d+\.\s*(.+)", blurbs_raw, re.MULTILINE)
        if len(parsed) >= len(products):
            blurbs = [re.sub(r"\s+", " ", b).strip() for b in parsed[:len(products)]]
        else:
            blurbs = parsed + fallback_blurbs[len(parsed):]
    else:
        blurbs = fallback_blurbs

    return {"title": title, "intro": intro, "blurbs": blurbs}


# ══════════════════════════════════════════════════════════════════════════════
# ARTICLE GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def generate_article(niche: str, data: dict, trends: dict,
                     month: str, dry_run: bool) -> bool:
    year, mo = month.split("-")
    month_fr  = MONTH_FR.get(mo, mo)
    niche_cfg = data.get("_niche_config", {}).get(niche, {})
    niche_label  = niche_cfg.get("label_fr", niche)
    slug_prefix  = niche_cfg.get("page_slug_prefix", niche.replace("_", "-"))
    category_hints = niche_cfg.get("category_hints", [])
    category_slug  = category_hints[0] if category_hints else niche

    print(f"\n  🔍 Niche : {niche}  ({niche_label})")
    products = fetch_diverse_products(niche, data, trends, count=5)

    if len(products) < 3:
        print(f"  ⚠️  Seulement {len(products)} produits — article ignoré")
        return False

    content = _generate_content(niche, niche_label, month_fr, year, products, data)
    title, intro, blurbs = content["title"], content["intro"], content["blurbs"]

    enriched = [
        {
            "id":        p["id"],
            "name":      p["name"],
            "brand":     p.get("brand"),
            "price":     p.get("price"),
            "url":       p.get("affiliate_url"),
            "partner":   p.get("merchant_key"),
            "image_url": p.get("image_url"),
            "rating":    p.get("rating"),
            "blurb_fr":  blurbs[i],
        }
        for i, p in enumerate(products)
    ]

    row = {
        "slug":          f"{slug_prefix}-{month}",
        "category_slug": category_slug,
        "subcategory":   niche_label,
        "keyword":       niche,
        "title_fr":      title,
        "intro_fr":      intro,
        "products":      json.dumps(enriched, ensure_ascii=False),
        "month":         month,
        "is_published":  True,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        print(f"  [DRY-RUN] {title}")
        print(f"  Intro  : {intro[:160]}…")
        for j, p in enumerate(enriched):
            print(f"    #{j+1} {p['name'][:60]}")
            print(f"       {p['blurb_fr'][:110]}")
        return True

    ok = sb_upsert("top5_articles", row)
    if ok:
        print(f"  ✅ Enregistré : {row['slug']}")
    return ok


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Génère des articles Top 5 par rotation de niche (lifestyle_niches.json)"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche les résultats sans écrire en base")
    parser.add_argument("--month",   default=datetime.now().strftime("%Y-%m"),
                        help="Mois cible (défaut: mois courant, ex: 2026-04)")
    parser.add_argument("--niche",   default=None,
                        help="Forcer une niche spécifique (ex: gaming_setup)")
    parser.add_argument("--count",   type=int, default=1,
                        help="Nombre d'articles à générer (défaut: 1)")
    args = parser.parse_args()

    llm_status = f"Ollama Cloud ({OLLAMA_MODEL})" if OLLAMA_API_KEY else "template (pas de clé LLM)"
    print(f"\n📝 Top 5 — {args.month}  |  LLM: {llm_status}  |  {args.count} article(s)")
    if args.dry_run:
        print("   Mode DRY-RUN\n")

    data   = _load_niches()
    trends = fetch_pinterest_trends()

    total = ok = 0
    used_niches: set = set()

    for i in range(args.count):
        # Pour la première itération, on peut forcer une niche
        forced = args.niche if i == 0 else None
        niche  = pick_niche(data, trends, forced=forced, exclude=used_niches)
        used_niches.add(niche)

        total += 1
        success = generate_article(niche, data, trends, args.month, args.dry_run)
        if success:
            ok += 1
            # Mise à jour last_used même en dry-run pour éviter les doublons
            data = mark_niche_used(niche, data)
            if not args.dry_run:
                _save_niches(data)
            else:
                print(f"  [DRY-RUN] last_used non sauvegardé pour '{niche}'")

        if i < args.count - 1:
            time.sleep(8)  # éviter back-to-back rate limit entre articles

    print(f"\n{'─'*54}")
    print(f"✅ {ok}/{total} articles générés — {args.month}\n")
    if args.dry_run and ok > 0:
        print("   (dry-run : aucun enregistrement en base)\n")


if __name__ == "__main__":
    main()
