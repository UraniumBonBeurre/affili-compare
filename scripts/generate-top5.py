#!/usr/bin/env python3
"""
generate-top5.py — Génère les articles "Top 5 du mois" par sous-catégorie
==========================================================================

Pipeline :
  1. Pour chaque sous-catégorie définie, récupère les 5 meilleurs produits
     (tri : rating DESC, review_count DESC) ayant un lien affilié
  2. Génère un titre + intro succincte via Ollama Cloud (minimax-m2.5:cloud)
     Fallback template si OLLAMA_CLOUD_API_KEY absent
  3. Upsert dans la table top5_articles de Supabase

Usage :
    python3 scripts/generate-top5.py                 # Mois en cours, toutes catégories
    python3 scripts/generate-top5.py --dry-run        # Affiche sans enregistrer
    python3 scripts/generate-top5.py --month 2026-03  # Mois spécifique
    python3 scripts/generate-top5.py --category gaming
    python3 scripts/generate-top5.py --limit 2        # Seulement 2 catégories (test)

Variables d'env (dans .env.local) :
    NEXT_PUBLIC_SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
    OLLAMA_CLOUD_API_KEY        (requis pour LLM, sinon → template)
    OLLAMA_CLOUD_HOST           (défaut: https://api.ollama.com)
    OLLAMA_CLOUD_MODEL          (défaut: minimax-m2.5:cloud)
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

try:
    import requests
except ImportError:
    print("❌  pip install requests python-dotenv")
    sys.exit(1)

# ── Chargement .env.local ─────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
for env_file in (ROOT / ".env.local", ROOT / ".env"):
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL      = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY      = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
OLLAMA_API_KEY    = os.environ.get("OLLAMA_CLOUD_API_KEY", "")
OLLAMA_HOST       = os.environ.get("OLLAMA_CLOUD_HOST", "https://api.ollama.com").rstrip("/")
OLLAMA_MODEL      = os.environ.get("OLLAMA_CLOUD_MODEL", "minimax-m2.5:cloud")
# Si le .env.local a gemini (pour generate-content.py), forcer minimax pour les Top 5
if OLLAMA_MODEL == "gemini-3-flash-preview:cloud":
    OLLAMA_MODEL = "minimax-m2.5:cloud"

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY manquants")
    sys.exit(1)

# ── Sous-catégories à traiter ─────────────────────────────────────────────────
# (slug_prefix, category_slug_db, label_fr, keyword)
SUBCATEGORIES = [
    ("meilleures-tv",             "tv-hifi",      "Télévisions",         "OLED QLED LCD television ecran"),
    ("meilleurs-casques-audio",   "tv-hifi",      "Casques audio",       "casque audio"),
    ("meilleures-enceintes",      "tv-hifi",      "Enceintes Bluetooth", "Escape JBL Tivoli SongBook bluetooth"),
    ("meilleurs-casques-gaming",  "gaming",       "Casques gaming",      "casque gaming"),
    ("meilleures-souris-gaming",  "gaming",       "Souris gaming",       "souris gaming"),
    ("meilleurs-tapis-souris",    "gaming",       "Tapis de souris",     "tapis souris"),
    ("meilleurs-pc-portables",    "informatique", "PC portables",        "portable laptop notebook"),
    ("meilleurs-claviers",        "informatique", "Claviers",            "clavier"),
    ("meilleures-souris-pc",      "informatique", "Souris PC",           "souris"),
    ("meilleurs-smartphones",     "smartphone",   "Smartphones",         "smartphone"),
]

SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

MONTH_FR = {
    "01": "janvier", "02": "février",   "03": "mars",    "04": "avril",
    "05": "mai",     "06": "juin",      "07": "juillet", "08": "août",
    "09": "septembre", "10": "octobre", "11": "novembre","12": "décembre",
}


# ── Helpers Supabase ──────────────────────────────────────────────────────────
def sb_get(path: str, params: str = "") -> list:
    url = f"{SUPABASE_URL}/rest/v1/{path}{'?' + params if params else ''}"
    r = requests.get(url, headers=SB_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def sb_upsert(table: str, row: dict) -> bool:
    headers = {**SB_HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"}
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers,
                      json=row, timeout=30)
    if r.status_code not in (200, 201, 204):
        print(f"  ⚠️  UPSERT {table}: HTTP {r.status_code} — {r.text[:200]}")
        return False
    return True


# ── Ollama Cloud LLM ──────────────────────────────────────────────────────────
def call_llm(prompt: str, max_tokens: int = 300) -> str | None:
    """
    Appelle Ollama Cloud (/api/chat) avec minimax-m2.5:cloud.
    Retourne None si la clé est absente ou en cas d'erreur (après 2 tentatives).
    """
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
                    "model":   OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream":  False,
                    "options": {"temperature": 0.5, "num_predict": max_tokens},
                },
                timeout=90,
            )
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"  ⏳ Rate limit (429) — attente {wait}s avant retry {attempt+1}/2…")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
        except Exception as e:
            if attempt < 2:
                print(f"  ⏳ Erreur LLM (tentative {attempt+1}/3): {e} — retry dans 8s…")
                time.sleep(8)
            else:
                print(f"  ⚠️  Ollama Cloud ({OLLAMA_MODEL}) échec définitif: {e}")
    return None


# ── Récupération des produits ─────────────────────────────────────────────────
def fetch_top5_products(category_slug: str, keyword: str) -> list[dict]:
    """
    Récupère les 5 meilleurs produits d'une catégorie ayant un lien affilié en stock.
    keyword : termes de recherche (ex : "casque audio") pour filtrer dans les noms.
    """
    # Construire un filtre OR sur les mots du keyword
    kw_words = [w for w in keyword.lower().split() if len(w) >= 3]
    if kw_words:
        or_filter = ",".join(f"name.ilike.*{w}*" for w in kw_words)
        extra = f"&or=({or_filter})"
    else:
        extra = ""

    products = sb_get(
        "products",
        f"category_slug=eq.{category_slug}"
        f"{extra}"
        "&order=rating.desc.nullslast,review_count.desc.nullslast"
        "&limit=50"
        "&select=id,name,brand,image_url,rating,review_count"
    )
    if not products:
        return []

    ids = ",".join(f'"{p["id"]}"' for p in products)
    links = sb_get(
        "affiliate_links",
        f"product_id=in.({ids})"
        "&in_stock=eq.true"
        "&price=not.is.null"
        "&order=price.asc"
        "&select=product_id,partner,price,currency,url"
    )
    # Garder le lien le moins cher par produit
    links_map: dict[str, dict] = {}
    for l in links:
        if l["product_id"] not in links_map:
            links_map[l["product_id"]] = l

    result = []
    for p in products:
        lnk = links_map.get(p["id"])
        if lnk:
            result.append({**p, "price": lnk["price"], "currency": lnk.get("currency", "EUR"),
                            "url": lnk["url"], "partner": lnk.get("partner", "")})
        if len(result) == 5:
            break
    return result


# ── Génération de texte ───────────────────────────────────────────────────────
def generate_intro(subcategory: str, month_fr: str, year: str, products: list[dict]) -> str:
    names = ", ".join(p["name"].split("(")[0].strip() for p in products[:3])
    fallback = (
        f"Découvrez notre sélection des 5 meilleurs {subcategory.lower()} de {month_fr} {year}. "
        f"Parmi nos coups de cœur ce mois-ci : {names}. "
        f"Prix mis à jour quotidiennement depuis les marchands partenaires."
    )
    prompt = (
        f"Rédige une introduction courte (2-3 phrases, style direct et utile, sans formules creuses) "
        f"pour un article intitulé \"Top 5 des meilleurs {subcategory.lower()} — {month_fr} {year}\". "
        f"Produits sélectionnés : {names}. "
        f"Concentre-toi sur la valeur pour l'acheteur. Réponds uniquement en français, sans titre."
    )
    result = call_llm(prompt, max_tokens=200)
    if result and len(result) > 30:
        result = re.sub(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+', '', result).strip()
    return result if result and len(result) > 30 else fallback


def generate_blurbs_batch(products: list[dict], subcategory: str) -> list[str]:
    """
    Génère les 5 blurbs en UN SEUL appel LLM (plus rapide, moins de rate-limit).
    Retourne une liste de 5 strings.
    """
    fallbacks = []
    for p in products:
        brand = p.get("brand") or ""
        price = p.get("price")
        rating = p.get("rating")
        r_str = f" noté {rating}/5" if rating else ""
        p_str = f" à partir de {price} €" if price else ""
        fallbacks.append(f"{brand} {p['name']}{r_str}{p_str}.".strip())

    lines = "\n".join(
        f"{i+1}. {p['name']} ({p.get('brand','')}, {p.get('price','?')} €)"
        for i, p in enumerate(products)
    )
    prompt = (
        f"Pour la catégorie «{subcategory}», génère une description courte (1 phrase, "
        f"style factuel, sans superlatif) pour chacun de ces {len(products)} produits.\n"
        f"Réponds UNIQUEMENT en français avec {len(products)} lignes numérotées, sans texte avant ni après :\n"
        + "\n".join(f"{i+1}. ..." for i in range(len(products)))
        + f"\n\nProduits :\n{lines}"
    )
    result = call_llm(prompt, max_tokens=600)
    if not result:
        return fallbacks

    # Strip any Chinese characters the model might inject
    result = re.sub(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+', '', result).strip()

    # Parser les lignes numérotées
    parsed = re.findall(r'^\d+\.\s*(.+)', result, re.MULTILINE)
    if len(parsed) >= len(products):
        return [re.sub(r'\s+', ' ', p).strip() for p in parsed[:len(products)]]
    return fallbacks


# ── Génération d'un article ───────────────────────────────────────────────────
def generate_article(slug_prefix: str, category_slug: str, subcategory: str,
                     keyword: str, month: str, dry_run: bool) -> bool:
    year, mo = month.split("-")
    month_fr = MONTH_FR.get(mo, mo)

    products = fetch_top5_products(category_slug, keyword)
    if len(products) < 3:
        print(f"  ⚠️  {len(products)} produits seulement pour «{subcategory}» — ignoré")
        return False
    print(f"  📦 {len(products)} produits trouvés")

    intro = generate_intro(subcategory, month_fr, year, products)
    time.sleep(4)  # avoid back-to-back rate limiting
    blurbs = generate_blurbs_batch(products, subcategory)

    enriched = []
    for i, p in enumerate(products):
        enriched.append({
            "id":       p["id"],
            "name":     p["name"],
            "brand":    p.get("brand"),
            "price":    p.get("price"),
            "url":      p.get("url"),
            "partner":  p.get("partner"),
            "image_url": p.get("image_url"),
            "rating":   p.get("rating"),
            "blurb_fr": blurbs[i],
        })

    row = {
        "slug":          f"{slug_prefix}-{month}",
        "category_slug": category_slug,
        "subcategory":   subcategory,
        "keyword":       keyword,
        "title_fr":      f"Top 5 des meilleurs {subcategory.lower()} — {month_fr} {year}",
        "intro_fr":      intro,
        "products":      json.dumps(enriched, ensure_ascii=False),
        "month":         month,
        "is_published":  True,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        print(f"  [DRY-RUN] {row['title_fr']}")
        print(f"  Intro  : {intro[:140]}…")
        for p in enriched:
            print(f"    #{enriched.index(p)+1} {p['name'][:60]}")
            print(f"       {p['blurb_fr'][:100]}")
        return True

    ok = sb_upsert("top5_articles", row)
    if ok:
        print(f"  ✅ Enregistré : {row['slug']}")
    return ok


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--month",     default=datetime.now().strftime("%Y-%m"))
    parser.add_argument("--category",  default=None, help="Filtrer par category_slug")
    parser.add_argument("--limit",     type=int, default=0, help="Max sous-catégories (0=toutes)")
    args = parser.parse_args()

    llm_status = f"Ollama Cloud ({OLLAMA_MODEL})" if OLLAMA_API_KEY else "template (OLLAMA_CLOUD_API_KEY absent)"
    print(f"\n📝 Top 5 — {args.month}  |  LLM: {llm_status}")
    if args.dry_run:
        print("   Mode DRY-RUN\n")

    total = ok = 0
    for i, (slug_prefix, cat_slug, subcategory, keyword) in enumerate(SUBCATEGORIES):
        if args.category and args.category != cat_slug:
            continue
        if args.limit and i >= args.limit:
            break
        print(f"\n[{cat_slug}] {subcategory}")
        total += 1
        if generate_article(slug_prefix, cat_slug, subcategory, keyword, args.month, args.dry_run):
            ok += 1
        time.sleep(8)  # avoid inter-article rate limiting

    print(f"\n{'─'*50}")
    print(f"✅ {ok}/{total} articles — {args.month}\n")


if __name__ == "__main__":
    main()
