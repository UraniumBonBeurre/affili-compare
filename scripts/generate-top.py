#!/usr/bin/env python3
"""
generate-top.py — Articles "Top N" par rotation de niche avec visuels & publication Pinterest
==============================================================================================

PIPELINE :
  1.  Charge config/lifestyle_niches.json
  2.  (si --use-pinterest-trends) Récupère les tendances Pinterest FR/US/GB/DE
  3.  Sélectionne la niche : score = days_since × weight × seasonal_boost × trend_affinity × jitter
  4.  Récupère --nb-products produits DIVERSIFIÉS via llm_niches (classifié par product_taxonomy.json)
  5.  Génère titre + intro + blurbs via Ollama Cloud (minimax-m2.5:cloud)
  6.  (si --create-visuals) Génère --nb-visuals visuels Pinterest 1000×1500 px
      - Visuel 1 : Hero (HF FLUX.1-schnell + overlay)
      - Visuel 2 : Spotlight produit #1
      - Visuel 3 : Checklist tous les produits
  7.  Upsert dans top5_articles (Supabase)
  8.  (si --publish-pinterest) Upload visuels vers R2 + publie pins sur Pinterest
      sinon : sauvegarde uniquement en local dans output/top_pins/
  9.  Met à jour last_used dans lifestyle_niches.json

USAGE :
    # Top 3, local, sans tendances ni visuels
    python3 scripts/generate-top.py \\
        --count 1 --nb-products 3 --month 2026-03 \\
        --no-use-pinterest-trends --no-create-visuals --no-publish-pinterest

    # Top 5, avec visuels locaux, tendances actives
    python3 scripts/generate-top.py \\
        --count 3 --nb-products 5 --month 2026-03 \\
        --use-pinterest-trends --create-visuals --nb-visuals 2 --no-publish-pinterest

    # Publication complète
    python3 scripts/generate-top.py \\
        --count 1 --nb-products 5 --month 2026-03 --niche gaming_setup \\
        --use-pinterest-trends --create-visuals --nb-visuals 3 --publish-pinterest

VARIABLES D'ENV (.env.local) :
    NEXT_PUBLIC_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
    OLLAMA_CLOUD_API_KEY
    PINTEREST_ACCESS_TOKEN, PINTEREST_API_BASE, PINTEREST_BOARD_ID
    HF_API_TOKEN (ou HF_TOKEN)  — génération images FLUX.1-schnell
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_PUBLIC_URL
    SITE_URL
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

try:
    import requests
except ImportError:
    print("❌  pip install requests")
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

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
HF_TOKEN        = os.environ.get("HF_API_TOKEN", "") or os.environ.get("HF_TOKEN", "")
PINTEREST_TOKEN = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
PINTEREST_BASE  = os.environ.get("PINTEREST_API_BASE", "https://api.pinterest.com/v5").rstrip("/")
PINTEREST_BOARD = os.environ.get("PINTEREST_BOARD_ID", "")
SITE_URL        = os.environ.get("SITE_URL", "https://affili-compare.com").rstrip("/")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌  NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY requis dans .env.local")
    sys.exit(1)

# ── Constantes ────────────────────────────────────────────────────────────────
NICHES_CFG   = ROOT / "config" / "lifestyle_niches.json"
TAXONOMY_CFG = ROOT / "config" / "product_taxonomy.json"
_TAXONOMY    = json.loads(TAXONOMY_CFG.read_text(encoding="utf-8")) if TAXONOMY_CFG.exists() else {}
OUTPUT_DIR   = ROOT / "output" / "top_pins"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Pinterest image dimensions (2:3)
PIN_W, PIN_H = 1000, 1500

TREND_REGIONS = ["FR", "US", "GB", "DE"]
TREND_TYPES   = ["growing", "monthly", "yearly"]

MONTH_FR = {
    "01": "janvier", "02": "février",   "03": "mars",    "04": "avril",
    "05": "mai",     "06": "juin",      "07": "juillet", "08": "août",
    "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre",
}

# Fonts: priorité pinterest-affiliate-bot, sinon affili-compare, sinon système
_FONTS_CANDIDATES = [
    ROOT.parent / "pinterest-affiliate-bot" / "assets" / "fonts",
    ROOT / "assets" / "fonts",
]
FONTS_DIR = next((p for p in _FONTS_CANDIDATES if p.exists()), Path("/System/Library/Fonts"))

_PRODUCT_SELECT = (
    "id,name,brand,image_url,rating,review_count,category_slug,"
    "affiliate_url,price,currency,merchant_key,description,llm_product_type"
)
_ORDER_QUALITY = "&order=rating.desc.nullslast,review_count.desc.nullslast,price.asc.nullslast"


# ══════════════════════════════════════════════════════════════════════════════
# ARGUMENT PARSING
# ══════════════════════════════════════════════════════════════════════════════

def _bool_arg(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("true", "1", "yes", "on"):
        return True
    if v.lower() in ("false", "0", "no", "off"):
        return False
    raise argparse.ArgumentTypeError(f"Valeur booléenne attendue (true/false), reçu: {v}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Génère des articles Top N avec visuels Pinterest et publication optionnelle",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ── Arguments obligatoires ─────────────────────────────────────────────
    parser.add_argument(
        "--count", type=int, required=True,
        help="Nombre d'articles à générer (ex: 3)",
    )
    parser.add_argument(
        "--nb-products", type=int, required=True,
        help="Nombre de produits par article top (ex: 3, 5, 10)",
    )
    parser.add_argument(
        "--month", required=True,
        help="Mois cible YYYY-MM (ex: 2026-03)",
    )

    # use_pinterest_trends — BooleanOptionalAction style manuel pour compatibilité 3.8+
    parser.add_argument(
        "--use-pinterest-trends", dest="use_pinterest_trends",
        type=_bool_arg, required=True,
        metavar="BOOL",
        help="Utiliser les tendances Pinterest pour pondérer les niches (true/false)",
    )
    parser.add_argument(
        "--create-visuals", dest="create_visuals",
        type=_bool_arg, required=True,
        metavar="BOOL",
        help="Générer les visuels Pinterest 1000×1500 px (true/false)",
    )
    parser.add_argument(
        "--nb-visuals", type=int, required=True,
        help="Nombre de visuels par article (1-3; ignoré si --create-visuals false)",
    )
    parser.add_argument(
        "--publish-pinterest", dest="publish_pinterest",
        type=_bool_arg, required=True,
        metavar="BOOL",
        help="Publier sur Pinterest + uploader en R2 (true) ou sauvegarder en local seulement (false)",
    )

    # ── Arguments optionnels ───────────────────────────────────────────────
    parser.add_argument(
        "--niche", default=None,
        help="Forcer une niche spécifique (ex: gaming_setup). Auto-sélection si absent.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche sans écrire en base ni publier (visuelle générée quand même localement).",
    )
    return parser


# ══════════════════════════════════════════════════════════════════════════════
# SUPABASE
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
# NICHE CONFIG
# ══════════════════════════════════════════════════════════════════════════════

def _load_niches() -> dict:
    if not NICHES_CFG.exists():
        print(f"❌  Config introuvable : {NICHES_CFG}")
        sys.exit(1)
    data = json.loads(NICHES_CFG.read_text(encoding="utf-8"))
    # Liste de niches canonique = product_taxonomy.json (source unique)
    if TAXONOMY_CFG.exists():
        taxonomy = json.loads(TAXONOMY_CFG.read_text(encoding="utf-8"))
        data["niches"] = list(taxonomy.get("niches", {}).keys())
    return data


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
    Retourne dict {keyword: {wow, mom, yoy, phase, score, region_count}}.
    Retourne {} si PINTEREST_ACCESS_TOKEN absent ou erreur.
    """
    if not PINTEREST_TOKEN:
        print("  ℹ️  PINTEREST_ACCESS_TOKEN absent — tendances ignorées")
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
                        if v is None: return None
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
    """Score = days_since × base_weight × seasonal_boost × trend_affinity × jitter"""
    import random

    if forced:
        if forced not in data.get("niches", []):
            print(f"  ⚠️  Niche '{forced}' inconnue — utilisée quand même")
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
    print(f"  📅 Mois {datetime.now().month}  |  Boostées: {_current_boosted(data)[:4]}")
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
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _pick_diverse(rows: list, count: int,
                  seen_ids: set = None, seen_types: set = None) -> list:
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


def fetch_diverse_products(niche: str, count: int = 5) -> list:
    """Requête via llm_niches + filtre product_type (niche_product_types de product_taxonomy.json)."""
    seen_ids:   set = set()
    seen_types: set = set()
    products:   list = []
    allowed_types = set(_TAXONOMY.get("niche_product_types", {}).get(niche, []))

    try:
        rows = sb_get("products",
                      f"llm_niches=cs.{{{niche}}}{_ORDER_QUALITY}"
                      f"&limit={count * 12}&active=not.is.false&select={_PRODUCT_SELECT}")
        if rows and allowed_types:
            filtered = [r for r in rows if r.get("llm_product_type") in allowed_types]
            if len(filtered) < len(rows):
                print(f"  🔍 product_type filter: {len(rows)} → {len(filtered)} ({len(rows)-len(filtered)} hors-niche exclus)")
            rows = filtered
        if rows:
            products = _pick_diverse(rows, count, seen_ids, seen_types)
    except Exception as e:
        print(f"  ⚠️  llm_niches query: {e}")

    if not products:
        hint = " — relancer classify-products.py" if not allowed_types or not products else ""
        print(f"  ⚠️  Aucun produit classifié pour '{niche}'{hint}")

    print(f"\n  📦 {len(products)} produits pour '{niche}' :")
    for i, p in enumerate(products[:count], 1):
        cat  = p.get("llm_product_type") or p.get("category_slug") or ""
        name = (p.get("name") or "")[:55]
        print(f"     {i}. [{cat}] {p.get('brand','?')} — {name} — {p.get('price','?')} €")
    return products[:count]


# ══════════════════════════════════════════════════════════════════════════════
# LLM — Ollama Cloud
# ══════════════════════════════════════════════════════════════════════════════

def _call_llm(prompt: str, max_tokens: int = 400) -> Optional[str]:
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
                      "options":  {"temperature": 0.55, "num_predict": max_tokens}},
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


def generate_content(niche: str, niche_label: str, month_fr: str, year: str,
                     products: list, data: dict) -> dict:
    n         = len(products)
    niche_cfg = data.get("_niche_config", {}).get(niche, {})
    template  = niche_cfg.get(
        "title_template",
        f"Top {n} incontournables pour {{label}} en {{month}} {{year}}"
    )
    title = template.format(n=n, label=niche_label, month=month_fr, year=year)

    product_list = "\n".join(
        f"{i+1}. {p.get('name','?')} ({p.get('brand','?')}, {p.get('price','?')} €)"
        for i, p in enumerate(products)
    )

    intro_fallback = (
        f"Découvrez notre sélection de {n} produits incontournables pour "
        f"{niche_label} en {month_fr} {year}. Des choix soigneusement sélectionnés "
        f"pour transformer votre quotidien avec des solutions pratiques et tendance."
    )
    intro = _call_llm(
        f"Tu rédiges une introduction courte (120-180 mots, ton naturel et enthousiaste, "
        f"style magazine) pour un article de blog intitulé :\n"
        f"« {title} »\n\n"
        f"Les {n} produits présentés sont :\n{product_list}\n\n"
        f"Écris uniquement en français, mets en valeur la diversité des produits "
        f"et ce qu'ils apportent concrètement à {niche_label}. "
        f"Pas de titre, directement le corps de l'intro.",
        380
    ) or intro_fallback
    time.sleep(4)

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
        blurbs = (
            [re.sub(r"\s+", " ", b).strip() for b in parsed[:n]]
            if len(parsed) >= n
            else parsed + fallback_blurbs[len(parsed):]
        )
    else:
        blurbs = fallback_blurbs

    return {"title": title, "intro": intro, "blurbs": blurbs}


# ══════════════════════════════════════════════════════════════════════════════
# VISUALS — Pinterest 1000×1500 px  (Pillow + HF FLUX.1-schnell)
# ══════════════════════════════════════════════════════════════════════════════

def _load_font(size: int, bold: bool = False):
    if not _PIL_AVAILABLE:
        return None
    candidates = []
    if bold:
        candidates = [
            FONTS_DIR / "Poppins-Bold.ttf",
            FONTS_DIR / "Montserrat-Bold.ttf",
            FONTS_DIR / "BebasNeue-Regular.ttf",
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


def _wrap(text: str, font, max_w: int, draw) -> list:
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


def _gradient_bg(top_color=(14, 20, 36), bot_color=(22, 32, 56)):
    img  = Image.new("RGB", (PIN_W, PIN_H))
    draw = ImageDraw.Draw(img)
    r0, g0, b0 = top_color
    r1, g1, b1 = bot_color
    for y in range(PIN_H):
        t = y / PIN_H
        draw.line([(0, y), (PIN_W, y)], fill=(
            int(r0 + (r1 - r0) * t), int(g0 + (g1 - g0) * t), int(b0 + (b1 - b0) * t),
        ))
    return img


def _generate_bg_hf(prompt: str) -> Optional["Image.Image"]:
    """Génère fond via HF FLUX.1-schnell. Retourne None si token absent ou échec."""
    if not HF_TOKEN:
        return None
    NO_TEXT = (
        "PURE PHOTOGRAPH. ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, NO SIGNS, "
        "NO LOGOS, NO WATERMARKS ANYWHERE IN THE IMAGE. "
        "Professional interior lifestyle photography only. Scene: "
    )
    url     = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {"inputs": NO_TEXT + prompt.strip(),
               "parameters": {"width": PIN_W, "height": PIN_H}}
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            if resp.status_code == 200:
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                return img.resize((PIN_W, PIN_H), Image.LANCZOS)
            elif resp.status_code == 503:
                wait = 20 * (attempt + 1)
                print(f"     HF en chargement — attente {wait}s…")
                time.sleep(wait)
            elif resp.status_code == 429:
                print("     Rate limit HF — attente 60s…")
                time.sleep(60)
            else:
                print(f"     HF erreur {resp.status_code}: {resp.text[:100]}")
                break
        except Exception as e:
            print(f"     HF réseau: {e}")
            time.sleep(10)
    return None


def _draw_watermark(draw) -> None:
    font  = _load_font(19)
    label = SITE_URL.replace("https://", "")
    w     = draw.textbbox((0, 0), label, font=font)[2]
    draw.text((PIN_W - w - 28, PIN_H - 38), label, font=font, fill=(130, 155, 185))


def _make_hero(title: str, nb: int, niche_label: str,
               month_fr: str, year: str, image_style: str, save_to: Path) -> str:
    print(f"  🖼️  Visuel Hero…")
    ACCENT = (16, 185, 129)
    WHITE  = (255, 255, 255)
    LGRAY  = (200, 220, 240)
    pad    = 52

    bg     = _generate_bg_hf(image_style) or _gradient_bg((14, 20, 38), (20, 35, 60))
    canvas = bg.copy()
    draw   = ImageDraw.Draw(canvas)

    ov_h = 430
    ov_y = PIN_H - ov_h
    blur_zone = bg.crop((0, ov_y - 30, PIN_W, PIN_H))
    blur_zone = blur_zone.filter(ImageFilter.GaussianBlur(radius=6))
    canvas.paste(blur_zone, (0, ov_y - 30))
    overlay = Image.new("RGBA", (PIN_W, ov_h), (12, 18, 32, 218))
    canvas.paste(Image.new("RGB", (PIN_W, ov_h), (12, 18, 32)), (0, ov_y), overlay.split()[3])

    y = ov_y + 36
    bf    = _load_font(21, bold=True)
    badge = f"✦  TOP {nb}  ·  {month_fr.upper()} {year}"
    bb    = draw.textbbox((0, 0), badge, font=bf)
    bw, bh = bb[2] + 26, bb[3] + 14
    draw.rounded_rectangle([pad, y, pad + bw, y + bh], radius=6, fill=ACCENT)
    draw.text((pad + 13, y + 7), badge, font=bf, fill=WHITE)
    y += bh + 24

    tf = _load_font(50, bold=True)
    for line in _wrap(title, tf, PIN_W - 2 * pad, draw)[:3]:
        lh = draw.textbbox((0, 0), line, font=tf)[3]
        draw.text((pad + 2, y + 2), line, font=tf, fill=(0, 0, 0))
        draw.text((pad, y), line, font=tf, fill=WHITE)
        y += lh + 8
    y += 12

    sf  = _load_font(27)
    sub = f"{nb} produits soigneusement sélectionnés pour {niche_label}"
    for line in _wrap(sub, sf, PIN_W - 2 * pad, draw)[:2]:
        draw.text((pad, y), line, font=sf, fill=LGRAY)
        y += draw.textbbox((0, 0), line, font=sf)[3] + 5

    draw.text((pad, PIN_H - 56), f"→  {SITE_URL.replace('https://', '')}/top",
              font=_load_font(22), fill=(100, 150, 190))
    _draw_watermark(draw)
    canvas.save(str(save_to), "JPEG", quality=90)
    print(f"     → {save_to.name}")
    return str(save_to)


def _make_spotlight(product: dict, title: str, niche_label: str,
                    month_fr: str, year: str, image_style: str, save_to: Path) -> str:
    print(f"  🖼️  Visuel Spotlight…")
    ACCENT = (16, 185, 129)
    WHITE  = (255, 255, 255)
    LGRAY  = (190, 210, 230)
    pad    = 52

    bg     = _generate_bg_hf(image_style + ", warm afternoon light, cinematic") \
             or _gradient_bg((28, 22, 48), (18, 14, 38))
    canvas = bg.copy()
    draw   = ImageDraw.Draw(canvas)

    for y_row in range(260):
        alpha = int(200 * (1 - y_row / 260))
        draw.line([(0, y_row), (PIN_W, y_row)], fill=(12, 16, 28))

    ov_h = 420
    ov_y = PIN_H - ov_h
    overlay = Image.new("RGBA", (PIN_W, ov_h), (10, 14, 26, 225))
    canvas.paste(Image.new("RGB", (PIN_W, ov_h), (10, 14, 26)), (0, ov_y), overlay.split()[3])

    draw.text((pad, 30), f"Pour {niche_label}  ·  {month_fr} {year}",
              font=_load_font(27), fill=(160, 220, 200))

    brand = (product.get("brand") or "").strip()
    if brand:
        draw.text((pad, 72), brand.upper(), font=_load_font(28), fill=ACCENT)

    name_f = _load_font(50, bold=True)
    name   = (product.get("name") or "")[:70]
    y_n    = 110
    for line in _wrap(name, name_f, PIN_W - 2 * pad, draw)[:2]:
        lh = draw.textbbox((0, 0), line, font=name_f)[3]
        draw.text((pad + 2, y_n + 2), line, font=name_f, fill=(0, 0, 0))
        draw.text((pad, y_n), line, font=name_f, fill=WHITE)
        y_n += lh + 8

    y = ov_y + 32
    price = product.get("price")
    if price:
        draw.text((pad, y), "À partir de", font=_load_font(23), fill=(150, 200, 185))
        y += 27
        pv_f  = _load_font(58, bold=True)
        price_txt = f"{price} €"
        draw.text((pad, y), price_txt, font=pv_f, fill=ACCENT)
        y += draw.textbbox((0, 0), price_txt, font=pv_f)[3] + 18

    ctx_f = _load_font(27)
    for line in _wrap(f"Inclus dans : « {title[:55]} »", ctx_f, PIN_W - 2 * pad, draw)[:2]:
        draw.text((pad, y), line, font=ctx_f, fill=LGRAY)
        y += draw.textbbox((0, 0), line, font=ctx_f)[3] + 5

    _draw_watermark(draw)
    canvas.save(str(save_to), "JPEG", quality=90)
    print(f"     → {save_to.name}")
    return str(save_to)


def _make_checklist(products: list, title: str, nb: int, niche_label: str,
                    month_fr: str, year: str, save_to: Path) -> str:
    print(f"  🖼️  Visuel Checklist…")
    ACCENT = (16, 185, 129)
    WHITE  = (255, 255, 255)
    LGRAY  = (195, 215, 235)
    DGRAY  = (40, 58, 80)
    pad    = 58

    canvas = _gradient_bg((10, 15, 28), (18, 26, 46))
    draw   = ImageDraw.Draw(canvas)

    y = 72
    bf    = _load_font(22, bold=True)
    badge = f"✦  TOP {nb}  ·  {month_fr.upper()} {year}"
    bb    = draw.textbbox((0, 0), badge, font=bf)
    bw, bh = bb[2] + 28, bb[3] + 14
    bx    = (PIN_W - bw) // 2
    draw.rounded_rectangle([bx, y, bx + bw, y + bh], radius=6, fill=ACCENT)
    draw.text((bx + 14, y + 7), badge, font=bf, fill=WHITE)
    y += bh + 30

    tf = _load_font(46, bold=True)
    for line in _wrap(title, tf, PIN_W - 2 * pad, draw)[:3]:
        lw = draw.textbbox((0, 0), line, font=tf)[2]
        lh = draw.textbbox((0, 0), line, font=tf)[3]
        draw.text(((PIN_W - lw) // 2, y), line, font=tf, fill=WHITE)
        y += lh + 6
    y += 26

    draw.line([(pad, y), (PIN_W - pad, y)], fill=ACCENT, width=2)
    y += 28

    num_f  = _load_font(38, bold=True)
    name_f = _load_font(30)
    brd_f  = _load_font(21)
    prc_f  = _load_font(26, bold=True)

    for i, p in enumerate(products[:nb]):
        circle_r = 28
        cx, cy   = pad + circle_r, y + circle_r
        draw.ellipse([(cx - circle_r, cy - circle_r), (cx + circle_r, cy + circle_r)],
                     fill=ACCENT)
        num_txt = str(i + 1)
        nb_bbox = draw.textbbox((0, 0), num_txt, font=num_f)
        draw.text(
            (cx - (nb_bbox[2] - nb_bbox[0]) // 2, cy - (nb_bbox[3] - nb_bbox[1]) // 2),
            num_txt, font=num_f, fill=WHITE,
        )
        tx, ty = pad + 2 * circle_r + 18, y
        brand  = (p.get("brand") or "").strip()
        name   = (p.get("name") or "").strip()
        price  = p.get("price")
        if brand:
            draw.text((tx, ty), brand, font=brd_f, fill=ACCENT)
            ty += 24
        for line in _wrap(name, name_f, PIN_W - tx - pad, draw)[:2]:
            draw.text((tx, ty), line, font=name_f, fill=LGRAY)
            ty += draw.textbbox((0, 0), line, font=name_f)[3] + 2
        if price:
            draw.text((tx, ty), f"{price} €", font=prc_f, fill=ACCENT)
            ty += 30
        item_bottom = max(y + 2 * circle_r, ty) + 14
        draw.line([(pad + 2 * circle_r + 10, item_bottom), (PIN_W - pad, item_bottom)],
                  fill=DGRAY, width=1)
        y = item_bottom + 16

    cta_f = _load_font(24)
    cta   = f"Voir l'article complet → {SITE_URL.replace('https://', '')}"
    cta_w = draw.textbbox((0, 0), cta, font=cta_f)[2]
    draw.text(((PIN_W - cta_w) // 2, PIN_H - 68), cta, font=cta_f, fill=(95, 145, 195))
    _draw_watermark(draw)
    canvas.save(str(save_to), "JPEG", quality=92)
    print(f"     → {save_to.name}")
    return str(save_to)


def generate_visuals(slug: str, title: str, nb_products: int, niche: str,
                     niche_label: str, month_fr: str, year: str,
                     products: list, data: dict, nb_visuals: int) -> list:
    """Génère jusqu'à nb_visuals (max 3) visuels Pinterest. Retourne les chemins locaux."""
    niche_cfg   = data.get("_niche_config", {}).get(niche, {})
    image_style = niche_cfg.get(
        "image_style",
        f"Modern interior design for {niche_label}, cozy lifestyle photography, no text",
    )
    slug_safe = re.sub(r"[^a-z0-9-]", "", slug.lower())[:42]
    nb        = min(nb_visuals, 3)
    variants  = [
        ("hero",      lambda: _make_hero(
            title, nb_products, niche_label, month_fr, year, image_style,
            OUTPUT_DIR / f"{slug_safe}_hero.jpg")),
        ("spotlight", lambda: _make_spotlight(
            products[0], title, niche_label, month_fr, year, image_style,
            OUTPUT_DIR / f"{slug_safe}_spotlight.jpg")),
        ("checklist", lambda: _make_checklist(
            products, title, nb_products, niche_label, month_fr, year,
            OUTPUT_DIR / f"{slug_safe}_checklist.jpg")),
    ]
    paths = []
    for _, fn in variants[:nb]:
        try:
            paths.append(fn())
        except Exception as e:
            print(f"  ⚠️  Visuel échoué : {e}")
    return paths


# ══════════════════════════════════════════════════════════════════════════════
# R2 UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def upload_to_r2(image_path: Path, key: str) -> str:
    """Upload vers Cloudflare R2. Retourne l'URL publique ou ''."""
    try:
        import boto3
        from botocore.config import Config

        r2_url    = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")
        account   = os.environ.get("R2_ACCOUNT_ID", "")
        key_id    = os.environ.get("R2_ACCESS_KEY_ID", "")
        secret    = os.environ.get("R2_SECRET_ACCESS_KEY", "")
        bucket    = os.environ.get("R2_BUCKET_NAME", "")

        if not all([r2_url, account, key_id, secret, bucket]):
            print("  ⚠️  Variables R2 manquantes (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, …)")
            return ""

        client = boto3.client(
            "s3",
            endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        with open(image_path, "rb") as f:
            client.put_object(
                Bucket=bucket, Key=key, Body=f.read(),
                ContentType="image/jpeg",
                CacheControl="public, max-age=2592000, immutable",
            )
        public_url = f"{r2_url}/{key}"
        print(f"  ☁️  R2 → {public_url}")
        return public_url
    except ImportError:
        print("  ⚠️  boto3 non installé — pip install boto3")
        return ""
    except Exception as e:
        print(f"  ⚠️  Upload R2 échoué : {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# PINTEREST PUBLISH
# ══════════════════════════════════════════════════════════════════════════════

def _publish_pin(board_id: str, title: str, description: str,
                 media_url: str, link: str) -> dict:
    """POST /pins via Pinterest API v5."""
    if not PINTEREST_TOKEN:
        raise RuntimeError("PINTEREST_ACCESS_TOKEN manquant")
    r = requests.post(
        f"{PINTEREST_BASE}/pins",
        headers={"Authorization": f"Bearer {PINTEREST_TOKEN}",
                 "Content-Type": "application/json"},
        json={
            "board_id":     board_id,
            "title":        title[:100],
            "description":  description[:500],
            "media_source": {"source_type": "image_url", "url": media_url},
            "link":         link,
        },
        timeout=30,
    )
    if r.status_code == 401:
        raise RuntimeError("Pinterest token expiré — `python3 scripts/refresh_pinterest_token.py`")
    if r.status_code == 429:
        raise RuntimeError("Pinterest rate limit (429)")
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Pinterest API {r.status_code}: {r.text[:300]}")
    return r.json()


def publish_visuals_pinterest(slug: str, title: str, niche: str, niche_label: str,
                               month: str, pin_paths: list, data: dict) -> list:
    """Upload chaque visuel sur R2 puis publie sur Pinterest. Retourne URLs publiées."""
    if not PINTEREST_BOARD:
        print("  ⚠️  PINTEREST_BOARD_ID manquant — publication ignorée")
        return []
    if not PINTEREST_TOKEN:
        print("  ⚠️  PINTEREST_ACCESS_TOKEN manquant — publication ignorée")
        return []

    niche_cfg   = data.get("_niche_config", {}).get(niche, {})
    description = niche_cfg.get("pinterest_description_fr", "").format(
        n=len(pin_paths),
        month=MONTH_FR.get(month.split("-")[1], ""),
        year=month.split("-")[0],
    )
    article_url = f"{SITE_URL}/top/{slug}"
    published   = []

    for i, local_path in enumerate(pin_paths):
        variant = Path(local_path).stem.split("_")[-1]  # hero/spotlight/checklist
        r2_key  = f"pins/top/{slug}_{variant}.jpg"
        r2_url  = upload_to_r2(Path(local_path), r2_key)
        if not r2_url:
            print(f"  ⚠️  Upload R2 échoué pour {variant} — pin ignoré")
            continue
        try:
            pin = _publish_pin(
                board_id    = PINTEREST_BOARD,
                title       = title,
                description = description or f"{title} — {niche_label}",
                media_url   = r2_url,
                link        = article_url,
            )
            pin_id = pin.get("id", "")
            print(f"  📌 Pin publié ({variant}): {pin_id}")
            published.append({"variant": variant, "r2_url": r2_url, "pin_id": pin_id})
            # Enregistrer dans supabase.pinterest_pins
            sb_upsert("pinterest_pins", {
                "pin_id":       pin_id,
                "board_id":     PINTEREST_BOARD,
                "image_url":    r2_url,
                "pin_url":      f"https://www.pinterest.com/pin/{pin_id}/",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "status":       "published",
            })
            if i < len(pin_paths) - 1:
                time.sleep(30)  # Pinterest rate limit safety
        except Exception as e:
            print(f"  ⚠️  Publication Pinterest ({variant}) échouée : {e}")

    return published


# ══════════════════════════════════════════════════════════════════════════════
# ARTICLE ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════

def run_article(niche: str, data: dict, trends: dict, args) -> bool:
    """Orchestre la génération d'un article complet pour une niche donnée."""
    year, mo  = args.month.split("-")
    month_fr  = MONTH_FR.get(mo, mo)
    niche_cfg = data.get("_niche_config", {}).get(niche, {})
    niche_label  = niche_cfg.get("label_fr", niche.replace("_", " "))
    slug_prefix  = niche_cfg.get("page_slug_prefix", niche.replace("_", "-"))
    slug = f"{slug_prefix}-{args.month}"

    print(f"\n  🔍 Niche : {niche}  ({niche_label})")

    # 1. Produits (llm_niches uniquement — source : product_taxonomy.json)
    products = fetch_diverse_products(niche, count=args.nb_products)
    if len(products) < min(3, args.nb_products):
        print(f"  ⚠️  Seulement {len(products)} produits (min {min(3, args.nb_products)} requis) — article ignoré")
        return False

    # Dériver category_slug depuis les produits retournés
    cats = [p.get("category_slug", "") for p in products if p.get("category_slug")]
    category_slug = max(set(cats), key=cats.count) if cats else niche

    # 2. Contenu LLM
    content = generate_content(niche, niche_label, month_fr, year, products, data)
    print(f"  📝 Titre : {content['title']}")

    # 3. Visuels
    pin_paths = []
    if args.create_visuals:
        if not _PIL_AVAILABLE:
            print("  ⚠️  Pillow non disponible — visuels ignorés (pip install Pillow)")
        else:
            nb_vis = max(1, min(args.nb_visuals, 3))
            print(f"\n  🎨 Génération de {nb_vis} visuel(s)…")
            pin_paths = generate_visuals(
                slug, content["title"], args.nb_products,
                niche, niche_label, month_fr, year,
                products, data, nb_vis,
            )

    # 4. Supabase upsert
    enriched = [
        {
            "id":        p["id"],
            "name":      p.get("name"),
            "brand":     p.get("brand"),
            "price":     p.get("price"),
            "url":       p.get("affiliate_url"),
            "partner":   p.get("merchant_key"),
            "image_url": p.get("image_url"),
            "rating":    p.get("rating"),
            "blurb_fr":  content["blurbs"][i] if i < len(content["blurbs"]) else "",
        }
        for i, p in enumerate(products)
    ]
    row = {
        "slug":          slug,
        "category_slug": category_slug,
        "subcategory":   niche_label,
        "keyword":       niche,
        "title_fr":      content["title"],
        "intro_fr":      content["intro"],
        "products":      json.dumps(enriched, ensure_ascii=False),
        "month":         args.month,
        "is_published":  True,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
    }

    if args.dry_run:
        print(f"\n  [DRY-RUN] Slug   : {slug}")
        print(f"  [DRY-RUN] Titre  : {content['title']}")
        print(f"  [DRY-RUN] Intro  : {content['intro'][:120]}…")
        for j, p in enumerate(enriched):
            print(f"    #{j+1} {p['name'][:55]} — {p.get('price','?')} €")
        if pin_paths:
            print(f"  [DRY-RUN] Images : {[Path(p).name for p in pin_paths]}")
        return True

    ok = sb_upsert("top5_articles", row)
    if ok:
        print(f"  ✅ Enregistré : {slug}")

    # 5. Publication Pinterest (si demandée et visuels présents)
    if args.publish_pinterest and pin_paths:
        print(f"\n  📌 Publication Pinterest ({len(pin_paths)} pin(s))…")
        published = publish_visuals_pinterest(
            slug, content["title"], niche, niche_label, args.month, pin_paths, data
        )
        if published:
            r2_urls = [p["r2_url"] for p in published]
            sb_upsert("top5_articles", {"slug": slug,
                                         "pin_images": json.dumps(r2_urls, ensure_ascii=False)})
    elif pin_paths:
        print(f"  💾 Visuels sauvegardés en local :")
        for p in pin_paths:
            print(f"       {p}")

    return ok


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    args = build_parser().parse_args()

    llm_info = f"Ollama Cloud ({OLLAMA_MODEL})" if OLLAMA_API_KEY else "template fallback"
    hf_info  = ("HF FLUX.1-schnell" if HF_TOKEN else "gradient fallback") if args.create_visuals else "désactivé"
    print(f"\n{'═'*62}")
    print(f"  🏆  generate-top.py  —  Top {args.nb_products}  —  {args.month}")
    print(f"  LLM     : {llm_info}")
    print(f"  Images  : {hf_info}  ({args.nb_visuals} par article)")
    print(f"  Trends  : {'Pinterest FR/US/GB/DE' if args.use_pinterest_trends else 'désactivés'}")
    print(f"  Publish : {'Pinterest + R2' if args.publish_pinterest else 'local seulement'}")
    if args.dry_run:
        print("  Mode    : DRY-RUN")
    print(f"{'═'*62}\n")

    data = _load_niches()

    # Tendances Pinterest
    trends = {}
    if args.use_pinterest_trends:
        print("📈 Récupération des tendances Pinterest…")
        trends = fetch_pinterest_trends()

    total = ok = 0
    used_niches: set = set()
    max_attempts = args.count * 5  # évite boucle infinie si pas assez de niches avec données
    attempts = 0

    while ok < args.count and attempts < max_attempts:
        attempts += 1
        forced = args.niche if attempts == 1 else None

        print(f"\n{'─'*62}")
        print(f"  [Article {ok+1}/{args.count}] Tentative {attempts}/{max_attempts} — Sélection de niche…")
        niche = pick_niche(data, trends, forced=forced, exclude=used_niches)
        used_niches.add(niche)

        total += 1
        success = run_article(niche, data, trends, args)
        if success:
            ok += 1
            data = mark_niche_used(niche, data)
            if not args.dry_run:
                _save_niches(data)

        if ok < args.count and attempts < max_attempts:
            time.sleep(8)

    print(f"\n{'═'*62}")
    print(f"  ✅  {ok}/{total} articles générés — {args.month}")
    if args.dry_run:
        print("  (dry-run : aucun enregistrement en base)")
    print(f"{'═'*62}\n")


if __name__ == "__main__":
    main()
