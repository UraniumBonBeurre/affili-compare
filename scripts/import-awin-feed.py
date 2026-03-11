#!/usr/bin/env python3
"""
import-awin-feed.py — Source unique de vérité pour MyGoodPick
=============================================================
Alimente Supabase directement depuis le flux produit Rue du Commerce (Awin).
Aucune donnée inventée — tout vient du flux réel.

Pré-requis dans .env.local
──────────────────────────
  AWIN_API_TOKEN       — Awin → My Account → API Access → "Create token"
  AWIN_PUBLISHER_ID    — Awin → My Account → Settings (ex: 2803450)

  # Pour le téléchargement du flux produit (ProductData API) :
  AWIN_PRODUCTDATA_KEY — Clé DISTINCTE de l'API token !
                         → Awin UI → Toolbox → Product Feeds
                           (ou Reports → Product Data → API Access)
                           Cliquer sur l'onglet "API" pour voir/générer la clé.
  AWIN_FEED_ID_RDC     — ID numérique du flux Rue du Commerce
                         → Awin UI → Toolbox → Product Feeds → Rue du Commerce
                           (colonne "Feed ID", ex: 655317)

  Si AWIN_FEED_ID_RDC n'est pas défini, le script tente une découverte auto.
  Si AWIN_PRODUCTDATA_KEY n'est pas défini, AWIN_API_TOKEN est utilisé en fallback.

Commandes disponibles
─────────────────────
  # Explorer le flux (rien n'est écrit en base)
  python scripts/import-awin-feed.py --discover "aspirateur sans fil" --limit 10
  python scripts/import-awin-feed.py --list-categories

  # Utiliser un fichier CSV téléchargé manuellement depuis Awin UI
  python scripts/import-awin-feed.py --local-feed /path/to/feed.csv \\
      --discover "aspirateur sans fil" --limit 10

  # Créer un comparatif réel depuis le flux
  python scripts/import-awin-feed.py --create-comparison \\
      --query "aspirateur sans fil" --limit 5 \\
      --slug "meilleurs-aspirateurs-sans-fil-2026" \\
      --title "Top 5 aspirateurs sans fil 2026" \\
      --category electromenager \\
      --subcategory "Aspirateurs sans fil"

  # Rafraîchir les prix des produits déjà en base
  python scripts/import-awin-feed.py --refresh-prices

  # Vider toute la base (irréversible)
  python scripts/import-awin-feed.py --reset --yes

  # Re-télécharger le flux (le flux est mis en cache 6h)
  python scripts/import-awin-feed.py --discover "robot" --force-download

Comment obtenir AWIN_FEED_ID_RDC et AWIN_PRODUCTDATA_KEY
─────────────────────────────────────────────────────────
  1. Connecte-toi sur https://ui.awin.com
  2. Va dans : Toolbox → Product Feeds  (ou cherche "Product Feeds" dans le menu)
  3. Cherche "Rue du Commerce" dans la liste des flux disponibles
  4. Note le Feed ID (première colonne) → AWIN_FEED_ID_RDC
  5. Clique sur l'onglet API (en haut de la page Product Feeds)
  6. Copie la clé affichée → AWIN_PRODUCTDATA_KEY
  7. Ajoute dans .env.local :
       AWIN_FEED_ID_RDC=655317     # ton ID réel
       AWIN_PRODUCTDATA_KEY=abc123 # ta clé ProductData réelle

  Alternative si l'API est inaccessible :
    Télécharge le CSV depuis Awin UI et utilise --local-feed /chemin/vers/feed.csv
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env.local")
except ImportError:
    pass

try:
    import requests
except ImportError:
    print("❌  pip install requests python-dotenv")
    sys.exit(1)

try:
    from supabase import create_client, Client
except ImportError:
    print("❌  pip install supabase")
    sys.exit(1)


# ── Credentials ───────────────────────────────────────────────────────────────

AWIN_API_TOKEN     = os.getenv("AWIN_API_TOKEN", "")
AWIN_PUBLISHER_ID  = os.getenv("AWIN_PUBLISHER_ID", "")
# ProductData API uses a SEPARATE key — see docstring for how to get it.
# Falls back to AWIN_API_TOKEN if not set (may fail if Awin enforces separation).
AWIN_PRODUCTDATA_KEY = os.getenv("AWIN_PRODUCTDATA_KEY") or AWIN_API_TOKEN
# Manual override for feed ID — avoids the often-broken discovery API
AWIN_FEED_ID_RDC   = os.getenv("AWIN_FEED_ID_RDC", "")

SUPABASE_URL      = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY      = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Rue du Commerce — programme Awin
RDC_PROGRAMME_ID = "6901"
RDC_PARTNER_KEY  = "rue-du-commerce"
RDC_COUNTRY      = "fr"

# Colonnes téléchargées depuis les flux Awin RdC
# Note: aw_deep_link = URL affiliée déjà construite par Awin (inclut awinaffid)
FEED_COLUMNS = ",".join([
    "aw_product_id", "product_name", "brand_name",
    "aw_image_url", "aw_thumb_url",
    "ean", "search_price", "currency",
    "merchant_deep_link", "aw_deep_link",
    "in_stock", "stock_quantity", "last_updated",
    "category_name", "description", "delivery_cost",
    "merchant_category", "average_rating", "reviews",
])

CACHE_DIR = Path(__file__).parent.parent / ".cache"
MERCHANTS_CONFIG_PATH = Path(__file__).parent.parent / "config" / "merchants.json"

# ── Merchant config ───────────────────────────────────────────────────────────

def _load_merchant_config(merchant_key: str) -> dict:
    """Charge la config d'un marchand depuis config/merchants.json."""
    if not MERCHANTS_CONFIG_PATH.exists():
        return {}
    data = json.loads(MERCHANTS_CONFIG_PATH.read_text(encoding="utf-8"))
    for m in data.get("merchants", []):
        if m.get("key") == merchant_key:
            return m
    return {}


def _infer_category_slug(merchant_cat: str) -> str:
    """Déduit le category_slug depuis merchant_category du flux Awin."""
    mc = merchant_cat.lower()
    if any(w in mc for w in ["tv", "télé", "hifi", "home cinéma", "enceinte", "barre de son", "ampli"]):
        return "tv-hifi"
    if any(w in mc for w in ["jeux vidéo", "gaming", "console", "manette"]):
        return "gaming"
    if any(w in mc for w in ["informatique", "ordinateur", "laptop", "portable", "imprimante", "clavier", "souris pc"]):
        return "informatique"
    if any(w in mc for w in ["smartphone", "téléphone", "mobile"]):
        return "smartphone"
    if any(w in mc for w in ["photo", "caméra", "vidéo"]):
        return "photo-video"
    if any(w in mc for w in ["électroménager", "cuisine", "réfrigér", "lave-", "four", "aspirateur", "robot"]):
        return "electromenager"
    if any(w in mc for w in ["maison", "jardin", "bricolage", "luminaire"]):
        return "maison-jardin"
    if any(w in mc for w in ["sécurité", "caméra ip", "surveillance", "alarme"]):
        return "securite"
    return "divers"


def _check_awin_credentials():
    missing = []
    if not AWIN_API_TOKEN:
        missing.append("AWIN_API_TOKEN   (Awin → My Account → API Access → Create token)")
    if not AWIN_PUBLISHER_ID:
        missing.append("AWIN_PUBLISHER_ID  (Awin → My Account → Settings → Publisher ID)")
    if missing:
        print("\n❌  Credentials Awin manquants dans .env.local :")
        for m in missing:
            print(f"   • {m}")
        print("\n   Une fois renseignés, relance la commande.")
        sys.exit(1)


def _check_supabase_credentials():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌  SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis dans .env.local")
        sys.exit(1)


# ── Awin feed download ────────────────────────────────────────────────────────

def _discover_feed_id(feed_name_hint: str = "en propre") -> Optional[str]:
    """
    Découvre l'ID du flux RdC via l'API legacydatafeeds.awin.com (format CSV).
    Utilise la clé AWIN_PRODUCTDATA_KEY.
    Préfère le flux correspondant à feed_name_hint (défaut: 'en propre' = produits directs).
    """
    url = f"https://legacydatafeeds.awin.com/datafeed/list/apikey/{AWIN_PRODUCTDATA_KEY}/format/csv/"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            return None
        import io
        reader = csv.DictReader(io.StringIO(resp.text))
        candidates = []
        for row in reader:
            adv_id = row.get("Advertiser ID", "").strip().strip('"')
            if adv_id == RDC_PROGRAMME_ID:
                fid  = row.get("Feed ID", "").strip().strip('"')
                name = row.get("Feed Name", "").strip().strip('"')
                nprods = row.get("No of products", "0").strip().strip('"')
                candidates.append((fid, name, int(nprods or 0)))
        if not candidates:
            return None
        # Priorité 1 : hint match
        for fid, name, _ in candidates:
            if feed_name_hint.lower() in name.lower():
                print(f"  🔍  Feed ID découvert : {fid} ({name})")
                return fid
        # Priorité 2 : plus petit (produits en propre = plus qualitatif)
        candidates.sort(key=lambda x: x[2])
        fid, name, n = candidates[0]
        print(f"  🔍  Feed ID découvert : {fid} ({name}, {n:,} produits)")
        return fid
    except Exception:
        return None


def _cache_path() -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"rdc_feed_{RDC_PROGRAMME_ID}.csv"


def _download_feed(feed_id: str) -> Path:
    """
    Télécharge le flux RdC (gzip CSV) et le décompresse dans le cache.
    URL format: /fid/{id}/format/csv/language/fr/compression/gzip/columns/...
    """
    cache = _cache_path()
    gz_cache = CACHE_DIR / f"rdc_feed_{RDC_PROGRAMME_ID}.csv.gz"
    from urllib.parse import quote as urlquote
    cols_encoded = urlquote(FEED_COLUMNS, safe="")
    url = (
        f"https://productdata.awin.com/datafeed/download"
        f"/apikey/{AWIN_PRODUCTDATA_KEY}"
        f"/fid/{feed_id}"
        f"/format/csv/language/fr"
        f"/delimiter/%2C/compression/gzip"
        f"/columns/{cols_encoded}/"
    )
    print(f"  ⬇  Téléchargement du flux Rue du Commerce (feed {feed_id})…")
    resp = requests.get(url, timeout=300, stream=True, allow_redirects=True)
    if resp.status_code == 401:
        print("❌  Clé ProductData invalide ou expirée (AWIN_PRODUCTDATA_KEY).")
        print("   → Va dans Awin UI → Toolbox → Product Feeds → onglet API")
        sys.exit(1)
    if resp.status_code == 403:
        print("❌  Accès refusé au flux. Vérifie que tu es approuvé sur ce programme.")
        sys.exit(1)
    if resp.status_code not in (200, 206):
        print(f"❌  Erreur HTTP {resp.status_code} lors du téléchargement du flux.")
        print(f"   URL : {url[:120]}")
        sys.exit(1)
    # Sauvegarde gzip
    with open(gz_cache, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
    # Décompression
    import gzip as gzip_lib
    with gzip_lib.open(gz_cache, "rt", encoding="utf-8", errors="replace") as gz:
        content = gz.read()
    with open(cache, "w", encoding="utf-8") as f:
        f.write(content)
    gz_cache.unlink(missing_ok=True)
    size_mb = cache.stat().st_size / 1024 / 1024
    print(f"  ✅  Flux mis en cache : {cache} ({size_mb:.1f} Mo)")
    return cache


def load_feed(force: bool = False, local_path: Optional[str] = None) -> list[dict]:
    """Charge le flux depuis un fichier local, le cache (< 6h), ou le télécharge."""
    # Priorité 1 : fichier local fourni explicitement
    if local_path:
        path = Path(local_path)
        if not path.exists():
            print(f"❌  Fichier introuvable : {local_path}")
            sys.exit(1)
        print(f"  📂  Lecture du fichier local : {path}")
        with open(path, encoding="utf-8", errors="replace") as f:
            rows = list(csv.DictReader(f))
        print(f"  → {len(rows):,} produits\n")
        return rows

    _check_awin_credentials()
    cache = _cache_path()

    # Priorité 2 : cache frais
    if not force and cache.exists():
        age_h = (time.time() - cache.stat().st_mtime) / 3600
        if age_h < 6:
            print(f"  📦  Flux en cache ({age_h:.1f}h) — utiliser --force-download pour rafraîchir")
            with open(cache, encoding="utf-8", errors="replace") as f:
                rows = list(csv.DictReader(f))
            print(f"  → {len(rows):,} produits dans le flux\n")
            return rows

    # Priorité 3 : AWIN_FEED_ID_RDC défini manuellement
    feed_id = AWIN_FEED_ID_RDC or _discover_feed_id()

    if not feed_id:
        print("\n❌  Feed ID Rue du Commerce introuvable.")
        print("   L'API ProductData Awin est actuellement instable (HTTP 500).")
        print()
        print("   Pour débloquer la situation, 2 options :")
        print()
        print("   Option A — Clé ProductData + Feed ID (recommandé) :")
        print("     1. Va sur https://ui.awin.com → Toolbox → Product Feeds")
        print("     2. Cherche 'Rue du Commerce' → note le Feed ID (ex: 655317)")
        print("     3. Onglet 'API' en haut → copie ta clé ProductData")
        print("     4. Ajoute dans .env.local :")
        print("          AWIN_FEED_ID_RDC=655317")
        print("          AWIN_PRODUCTDATA_KEY=ta_cle_productdata")
        print()
        print("   Option B — Téléchargement manuel :")
        print("     1. Dans Awin UI → Product Feeds → télécharge le CSV de RdC")
        print("     2. Lance : python scripts/import-awin-feed.py --local-feed /chemin/feed.csv ...")
        sys.exit(1)

    cache = _download_feed(feed_id)
    with open(cache, encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
    print(f"  → {len(rows):,} produits dans le flux\n")
    return rows


# ── Matching / scoring ────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\u00c0-\u00ff ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _get_category(row: dict) -> str:
    """merchant_category est renseigné dans les flux RdC, category_name est souvent vide."""
    return row.get("merchant_category") or row.get("category_name") or "Divers"


def _score(row: dict, tokens: list[str]) -> int:
    name = _normalize(row.get("product_name", ""))
    return sum(1 for t in tokens if t in name)


def _search(rows: list[dict], query: str, limit: int,
            feed_category: str = "", min_price: float = 0.0) -> list[dict]:
    # Pré-filtre par merchant_category si spécifié
    if feed_category:
        fc_norm = _normalize(feed_category)
        pool = [r for r in rows if _normalize(_get_category(r)) == fc_norm]
        if not pool:
            # Fallback : contenance partielle
            pool = [r for r in rows if fc_norm in _normalize(_get_category(r))]
    else:
        pool = rows

    # Filtre prix minimum
    if min_price > 0:
        pool = [r for r in pool if (_parse_price(r.get("search_price", "0")) or 0) >= min_price]

    if not query.strip():
        # Pas de requête texte → tous les produits de la catégorie, triés par prix desc
        pool_with_price = [(r, _parse_price(r.get("search_price", "0")) or 0) for r in pool]
        pool_with_price.sort(key=lambda x: -x[1])
        return [r for r, _ in pool_with_price[:limit]]

    tokens = _normalize(query).split()
    # Tous les tokens présents → score maximum
    full = [(r, _score(r, tokens)) for r in pool if _score(r, tokens) >= len(tokens)]
    if not full:
        # Fallback : au moins 1 token
        full = [(r, s) for r in pool if (s := _score(r, tokens)) > 0]
    if not full:
        # Fallback 2 : toute la catégorie triée par prix desc
        full = [(r, 0) for r in pool]
    full.sort(key=lambda x: (-x[1], -(_parse_price(x[0].get("search_price", "0")) or 0)))
    return [r for r, _ in full[:limit]]


def _parse_price(price_str: str) -> Optional[float]:
    try:
        return round(float(price_str.replace(",", ".").strip()), 2)
    except (ValueError, AttributeError):
        return None


def _is_in_stock(row: dict) -> bool:
    val = (row.get("in_stock") or row.get("stock_status") or "").lower().strip()
    return val in ("1", "yes", "true", "en stock", "in stock")


def _tracking_url(row: dict) -> str:
    """
    Retourne l'URL affiliée.
    Priorité 1 : aw_deep_link (déjà construit par Awin, inclut awinaffid)
    Priorité 2 : construit depuis merchant_deep_link
    """
    aw = (row.get("aw_deep_link") or "").strip()
    if aw:
        return aw
    raw = (row.get("merchant_deep_link") or "").strip()
    if raw:
        return (
            f"https://www.awin1.com/cread.php"
            f"?awinmid={RDC_PROGRAMME_ID}&awinaffid={AWIN_PUBLISHER_ID}"
            f"&ued={quote(raw, safe='')}"
        )
    return ""


# ── Supabase helpers ──────────────────────────────────────────────────────────

_sb_client: Optional[Client] = None


def _sb() -> Client:
    global _sb_client
    if _sb_client is None:
        _check_supabase_credentials()
        _sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sb_client


def _upsert_category(slug: str, name_fr: str, icon: str = "🛒") -> dict:
    sb = _sb()
    existing = sb.table("categories").select("*").eq("slug", slug).limit(1).execute()
    if existing.data:
        return existing.data[0]
    res = sb.table("categories").insert({
        "slug": slug, "name_fr": name_fr, "name_en": name_fr, "name_de": name_fr,
        "icon": icon, "is_active": True, "display_order": 0,
    }).execute()
    return res.data[0]


def _upsert_comparison(slug: str, category_id: str, title_fr: str, subcategory: str = "") -> dict:
    sb = _sb()
    payload = {
        "slug": slug, "category_id": category_id,
        "title_fr": title_fr, "title_en": title_fr, "title_de": title_fr,
        "is_published": True, "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    if subcategory:
        payload["subcategory"] = subcategory
    existing = sb.table("comparisons").select("id").eq("slug", slug).limit(1).execute()
    if existing.data:
        rid = existing.data[0]["id"]
        sb.table("comparisons").update(payload).eq("id", rid).execute()
        return sb.table("comparisons").select("*").eq("id", rid).limit(1).execute().data[0]
    return sb.table("comparisons").insert(payload).execute().data[0]


def _generate_embedding(text: str) -> Optional[list]:
    """
    Génère un embedding 384-dims via sentence-transformers (gratuit, local).
    Retourne None si sentence-transformers n'est pas installé (non bloquant).
    Convention E5 : préfixer avec "passage: " pour les documents produit.
    """
    try:
        from sentence_transformers import SentenceTransformer
        model = _generate_embedding._model  # type: ignore[attr-defined]
    except AttributeError:
        try:
            from sentence_transformers import SentenceTransformer
            print("   📦 Chargement du modèle d'embedding (1re fois, ~10s)…")
            _generate_embedding._model = SentenceTransformer("intfloat/multilingual-e5-small")
            model = _generate_embedding._model
        except ImportError:
            return None
    prefixed = f"passage: {text}"
    vec = model.encode([prefixed], normalize_embeddings=True)[0]
    return vec.tolist()


def _upsert_product(name: str, brand: str, image_url: str = "",
                    rating: Optional[float] = None, review_count: int = 0,
                    category_slug: str = "") -> dict:
    sb = _sb()
    existing = sb.table("products").select("*").eq("name", name[:200]).limit(1).execute()
    payload: dict = {
        "name": name[:200],
        "brand": (brand or "—")[:100],
        "image_url": image_url or None,
        "pros_fr": json.dumps([], ensure_ascii=False),
        "cons_fr": json.dumps([], ensure_ascii=False),
        "review_count": review_count,
    }
    if rating is not None:
        payload["rating"] = rating
    if category_slug:
        payload["category_slug"] = category_slug

    # Construire le rich_text et l'embedding
    rich_text_parts = [name[:200]]
    if brand:
        rich_text_parts.append(f"Marque: {brand}")
    if category_slug:
        rich_text_parts.append(f"Catégorie: {category_slug.replace('-', ' ')}")
    rich_text = f"passage: {' — '.join(rich_text_parts)}"
    payload["rich_text"] = rich_text

    embedding = _generate_embedding(rich_text.replace("passage: ", ""))
    if embedding is not None:
        payload["embedding"] = embedding

    if existing.data:
        rid = existing.data[0]["id"]
        sb.table("products").update(payload).eq("id", rid).execute()
        return sb.table("products").select("*").eq("id", rid).limit(1).execute().data[0]
    return sb.table("products").insert(payload).execute().data[0]


def _upsert_comparison_product(comparison_id: str, product_id: str, position: int):
    sb = _sb()
    existing = (
        sb.table("comparison_products").select("id")
        .eq("comparison_id", comparison_id).eq("product_id", product_id)
        .limit(1).execute()
    )
    if existing.data:
        sb.table("comparison_products").update({"position": position}).eq("id", existing.data[0]["id"]).execute()
    else:
        sb.table("comparison_products").insert({
            "comparison_id": comparison_id, "product_id": product_id, "position": position,
        }).execute()


def _upsert_affiliate_link(product_id: str, comparison_id: str, url: str,
                           price: Optional[float], in_stock: bool):
    sb = _sb()
    payload = {
        "product_id": product_id, "comparison_id": comparison_id,
        "partner": RDC_PARTNER_KEY, "country": RDC_COUNTRY,
        "url": url, "price": price, "currency": "EUR",
        "in_stock": in_stock, "commission_rate": 3.0,
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }
    # Clé unique : (product_id, comparison_id, partner) — un lien par comparatif
    existing = (
        sb.table("affiliate_links").select("id")
        .eq("product_id", product_id)
        .eq("comparison_id", comparison_id)
        .eq("partner", RDC_PARTNER_KEY)
        .limit(1).execute()
    )
    if existing.data:
        sb.table("affiliate_links").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        sb.table("affiliate_links").insert(payload).execute()


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_discover(query: str, limit: int, force: bool, local_path: Optional[str] = None):
    rows = load_feed(force, local_path)
    matches = _search(rows, query, limit)
    if not matches:
        print(f"  Aucun produit trouvé pour '{query}'.")
        return
    print(f"🔍  {len(matches)} résultats pour '{query}' :\n")
    for i, row in enumerate(matches, 1):
        price = _parse_price(row.get("search_price", ""))
        stock = "✅" if _is_in_stock(row) else "❌"
        name  = row.get("product_name", "")[:80]
        brand = row.get("brand_name", "")
        cat   = _get_category(row)
        url   = (row.get("aw_deep_link") or row.get("merchant_deep_link") or "")[:80]
        print(f"  {i:2}. {stock}  {(price or 0):8.2f} €  [{brand}]")
        print(f"       {name}")
        print(f"       Catégorie feed : {cat}")
        print(f"       URL : {url}")
        print()


def cmd_list_categories(force: bool, local_path: Optional[str] = None):
    rows = load_feed(force, local_path)
    cats = Counter(_get_category(r) for r in rows)
    print(f"📂  {len(cats)} catégories dans le flux Rue du Commerce :\n")
    for cat, count in cats.most_common(60):
        print(f"  {count:7,d}  {cat}")


def cmd_create_comparison(query: str, slug: str, title: str, category_slug: str,
                          subcategory: str, limit: int, dry_run: bool, force: bool,
                          local_path: Optional[str] = None,
                          feed_category: str = "", min_price: float = 0.0):
    rows = load_feed(force, local_path)
    matches = _search(rows, query, limit, feed_category=feed_category, min_price=min_price)

    if not matches:
        print(f"❌  Aucun produit trouvé pour la requête '{query}'.")
        print("    Essaie --discover avec d'autres mots-clés.")
        return

    print(f"{'[DRY-RUN] ' if dry_run else ''}🏗   Comparatif : {title}")
    print(f"   Slug     : {slug}")
    print(f"   Catégorie: {category_slug}  |  Sous-cat: {subcategory or '—'}\n")
    print(f"   {len(matches)} produits sélectionnés :\n")

    for i, row in enumerate(matches, 1):
        price = _parse_price(row.get("search_price", ""))
        stock = "✅" if _is_in_stock(row) else "❌"
        brand = row.get("brand_name", "")
        name  = row.get("product_name", "")[:80]
        print(f"   {i}. {stock}  {(price or 0):.2f} €  [{brand}] {name}")

    if dry_run:
        print("\n  Mode dry-run : rien écrit en base.")
        return

    print()
    cat  = _upsert_category(category_slug, category_slug.replace("-", " ").title())
    comp = _upsert_comparison(slug, cat["id"], title, subcategory)
    print(f"  📂 Catégorie : {cat['name_fr']} ({cat['id']})")
    print(f"  📄 Comparatif : {comp['slug']} ({comp['id']})\n")

    # Nettoyer AVANT d'insérer les nouveaux produits
    sb0 = _sb()
    sb0.table("comparison_products").delete().eq("comparison_id", comp["id"]).execute()
    sb0.table("affiliate_links").delete().eq("comparison_id", comp["id"]).execute()

    for pos, row in enumerate(matches, 1):
        name    = row.get("product_name", "").strip()
        brand   = row.get("brand_name", "").strip()
        image   = (row.get("aw_image_url") or row.get("aw_thumb_url") or "").strip()
        price   = _parse_price(row.get("search_price", ""))
        in_stk  = _is_in_stock(row)

        tracked = _tracking_url(row)
        if not name or not tracked:
            print(f"  {pos}. ⚠   Produit ignoré (nom ou URL manquant)")
            continue

        # Notes depuis le flux
        raw_rating = row.get("average_rating", "").strip()
        try:
            rating = float(raw_rating) if raw_rating else None
            if rating is not None and not (0 <= rating <= 5):
                rating = min(5.0, max(0.0, rating))
        except ValueError:
            rating = None
        raw_reviews = row.get("reviews", "0").strip()
        try:
            review_count = int(float(raw_reviews)) if raw_reviews else 0
        except (ValueError, TypeError):
            review_count = 0

        product = _upsert_product(name, brand, image, rating=rating, review_count=review_count, category_slug=category_slug)
        _upsert_comparison_product(comp["id"], product["id"], pos)
        _upsert_affiliate_link(product["id"], comp["id"], tracked, price, in_stk)

        stock_label = "en stock" if in_stk else "hors stock"
        print(f"  {pos}. ✅  {(price or 0):.2f} €  [{brand}] {name[:60]}")
        print(f"       {stock_label}")

    print(f"\n✅  Terminé — visite : /fr/{category_slug}/{slug}")


def cmd_refresh_prices(force: bool, local_path: Optional[str] = None):
    rows = load_feed(force, local_path)
    sb = _sb()

    links_res = sb.table("affiliate_links").select("id,product_id").eq("partner", RDC_PARTNER_KEY).execute()
    if not links_res.data:
        print("Aucun lien Rue du Commerce en base — crée d'abord un comparatif avec --create-comparison.")
        return

    product_ids = {l["product_id"] for l in links_res.data}
    products_res = sb.table("products").select("id,name,brand").execute()
    products = [p for p in (products_res.data or []) if p["id"] in product_ids]

    print(f"🔄  Rafraîchissement de {len(products)} produits…\n")
    updated = 0
    for product in products:
        matches = _search(rows, product["name"], 1)
        if not matches:
            print(f"  ⚠   Pas de match feed pour : {product['name'][:60]}")
            continue

        row     = matches[0]
        price   = _parse_price(row.get("search_price", ""))
        tracked = _tracking_url(row)
        in_stk  = _is_in_stock(row)
        image   = (row.get("aw_image_url") or row.get("aw_thumb_url") or "").strip()

        if not tracked:
            continue

        # Update image if missing
        prod_full = sb.table("products").select("image_url").eq("id", product["id"]).single().execute().data
        if not prod_full.get("image_url") and image:
            sb.table("products").update({"image_url": image}).eq("id", product["id"]).execute()

        # Update link
        link_existing = (
            sb.table("affiliate_links").select("id")
            .eq("product_id", product["id"]).eq("partner", RDC_PARTNER_KEY)
            .limit(1).execute()
        )
        payload = {
            "url": tracked, "price": price, "in_stock": in_stk,
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }
        if link_existing.data:
            sb.table("affiliate_links").update(payload).eq("id", link_existing.data[0]["id"]).execute()
        updated += 1
        print(f"  ✅  {product['name'][:60]} → {(price or 0):.2f} €  ({'✅' if in_stk else '❌'})")

    print(f"\n✅  {updated}/{len(products)} produits mis à jour.")


def cmd_reset(yes: bool):
    _check_supabase_credentials()
    if not yes:
        answer = input("  ⚠  Cette action supprime TOUTES les données. Taper 'RESET' pour confirmer : ")
        if answer.strip() != "RESET":
            print("  Annulé.")
            return
    sb = _sb()
    print("🗑   Suppression en cours…")
    for table in ["affiliate_links", "comparison_products", "comparisons", "products", "categories"]:
        sb.table(table).delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        print(f"  ✅  {table} vidée")
    print("\n✅  Base vidée. Crée des comparatifs avec --create-comparison.")


# ── Bulk import ──────────────────────────────────────────────────────────────

DEFAULT_BULK_LIMIT = 500  # produits par run — raisonnable pour N partenaires quotidiens


def cmd_bulk_import(merchant_key: str, limit: int, dry_run: bool, force: bool,
                   local_path: Optional[str] = None, category_filter: str = ""):
    """
    Import incrémental depuis le flux Awin d'un marchand.

    Stratégie :
      1. Trie le flux par last_updated DESC (produits récents en premier)
      2. Récupère les external_id déjà en base → saute les produits connus
      3. Insère jusqu'à `limit` nouveaux produits par run

    Avec --limit 500 (défaut) et un run quotidien :
      • Initialisation : plusieurs runs pour couvrir tout le catalogue
      • Quotidien      : seuls les !nouveaux produits depuis la veille sont insérés
    """
    rows = load_feed(force, local_path)

    # Normaliser les noms de colonnes (certains flux ont des espaces en tête)
    if rows and any(k is not None and k != k.strip() for k in rows[0]):
        rows = [{(k.strip() if k else k): v for k, v in row.items()} for row in rows]

    # Si le flux n'a pas de catégories, injecter la catégorie par défaut du marchand
    merchant_cfg = _load_merchant_config(merchant_key)
    default_cat  = (merchant_cfg.get("default_category") or "").strip()
    if default_cat:
        no_cat_count = sum(1 for r in rows if not (r.get("merchant_category") or r.get("category_name") or "").strip())
        if no_cat_count:
            for r in rows:
                if not (r.get("merchant_category") or r.get("category_name") or "").strip():
                    r["merchant_category"] = default_cat
            print(f"   ℹ  Catégorie par défaut \"{default_cat}\" injectée sur {no_cat_count:,} produits")

    # Trier par last_updated DESC → nouvelles références en premier
    def _parse_dt(s: str):
        try:
            return datetime.fromisoformat(s.strip().replace(" ", "T"))
        except Exception:
            return datetime.min

    rows_sorted = sorted(rows, key=lambda r: _parse_dt(r.get("last_updated", "")), reverse=True)

    # Filtre optionnel par catégorie (argument CLI)
    if category_filter:
        cf = category_filter.lower()
        rows_sorted = [r for r in rows_sorted if cf in _get_category(r).lower()]

    # Filtre par config/merchant-categories.json (false = exclu)
    cat_config_path = Path(__file__).parent.parent / "config" / "merchant-categories.json"
    if cat_config_path.exists():
        try:
            cat_config = json.loads(cat_config_path.read_text(encoding="utf-8"))
            merchant_cats = cat_config.get(merchant_key, {})
            if merchant_cats:
                # Seules les catégories explicitement fausses sont retirées
                excluded = {k for k, v in merchant_cats.items() if v is False}
                if excluded:
                    before = len(rows_sorted)
                    rows_sorted = [r for r in rows_sorted if _get_category(r) not in excluded]
                    print(f"   Catégories exclues: {len(excluded)}  ({before - len(rows_sorted):,} produits filtrés)")
        except (json.JSONDecodeError, OSError):
            pass

    # Produits déjà en base (par external_id)
    known_ids: set = set()
    sb = None
    if not dry_run:
        sb = _sb()
        res = sb.table("products").select("external_id").not_.is_("external_id", "null").execute()
        known_ids = {r["external_id"] for r in (res.data or []) if r.get("external_id")}

    total_feed      = len(rows_sorted)
    already_in_db   = sum(1 for r in rows_sorted if (r.get("aw_product_id") or "").strip() in known_ids)
    new_available   = total_feed - already_in_db

    print(f"{'[DRY-RUN] ' if dry_run else ''}📦  Import incrémental — marchand : {merchant_key}")
    print(f"   Flux total   : {total_feed:>8,} produits")
    print(f"   Déjà en base : {already_in_db:>8,} produits  (sautés)")
    print(f"   Nouveaux     : {new_available:>8,} disponibles")
    print(f"   Ce run       : {min(limit, new_available):>8,} à importer (limite = {limit})")
    print()

    imported       = 0
    skipped_dup    = 0
    skipped_invalid = 0

    for row in rows_sorted:
        if imported >= limit:
            break

        ext_id = (row.get("aw_product_id") or "").strip()
        if not ext_id:
            skipped_invalid += 1
            continue

        if ext_id in known_ids:
            skipped_dup += 1
            continue

        name = (row.get("product_name") or "").strip()
        if not name:
            skipped_invalid += 1
            continue

        brand        = (row.get("brand_name") or "").strip()
        image        = (row.get("aw_image_url") or row.get("aw_thumb_url") or "").strip()
        ean          = (row.get("ean") or "").strip() or None
        last_updated = (row.get("last_updated") or "").strip() or None

        raw_rating = (row.get("average_rating") or "").strip()
        try:
            rating: Optional[float] = float(raw_rating) if raw_rating else None
            if rating is not None:
                rating = round(min(5.0, max(0.0, rating)), 2)
        except ValueError:
            rating = None

        try:
            review_count = int(float(row.get("reviews") or "0"))
        except (ValueError, TypeError):
            review_count = 0

        category_slug = _infer_category_slug(_get_category(row))

        if dry_run:
            print(f"  [{imported + 1:4d}] {name[:72]}")
            print(f"         {brand or '—'} | {(_parse_price(row.get('search_price','')) or 0):.2f}€"
                  f" | EAN: {ean or '—'} | catégorie: {category_slug}"
                  f" | {last_updated or '—'}")
            imported += 1
            known_ids.add(ext_id)
            continue

        payload: dict = {
            "name":         name[:200],
            "brand":        (brand or "—")[:100],
            "image_url":    image or None,
            "external_id":  ext_id,
            "ean":          ean,
            "rating":       rating,
            "review_count": review_count,
            "category_slug": category_slug,
            "pros_fr":      json.dumps([], ensure_ascii=False),
            "cons_fr":      json.dumps([], ensure_ascii=False),
        }

        # Upsert par external_id
        existing = sb.table("products").select("id").eq("external_id", ext_id).limit(1).execute()  # type: ignore[union-attr]
        if existing.data:
            sb.table("products").update(payload).eq("id", existing.data[0]["id"]).execute()  # type: ignore[union-attr]
        else:
            sb.table("products").insert(payload).execute()  # type: ignore[union-attr]

        known_ids.add(ext_id)
        imported += 1
        if imported % 50 == 0:
            print(f"   … {imported} produits importés")

    remaining = max(0, new_available - imported)
    tag = "(simulés) " if dry_run else ""
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}✅  {imported} produits {tag}importés")
    if remaining > 0:
        print(f"   ~{remaining:,} restants — relance le script pour continuer")
        print(f"   (ou utilise --limit {min(remaining + imported, 5000)} pour tout importer en une fois)")
    else:
        print("   ✨  Catalogue à jour pour ce marchand.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Flux Awin Rue du Commerce → Supabase MyGoodPick",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--merchant",            default="rue-du-commerce", metavar="KEY",
                                            help="Clé marchand (config/merchants.json) — défaut: rue-du-commerce")
    p.add_argument("--bulk-import",         action="store_true",
                                            help=f"Import incrémental (nouveaux produits en premier, défaut: {DEFAULT_BULK_LIMIT} par run)")
    p.add_argument("--discover",            metavar="QUERY", help="Chercher des produits dans le flux")
    p.add_argument("--list-categories",     action="store_true", help="Lister les catégories du flux")
    p.add_argument("--create-comparison",   action="store_true", help="Créer un comparatif depuis le flux")
    p.add_argument("--refresh-prices",      action="store_true", help="Mettre à jour les prix existants")
    p.add_argument("--reset",               action="store_true", help="Vider toute la base (DANGER)")
    p.add_argument("--query",               default="", help="Mots-clés de recherche (peut être vide si --feed-category est fourni)")
    p.add_argument("--slug",                help="Slug du comparatif")
    p.add_argument("--title",               help="Titre du comparatif")
    p.add_argument("--category",            dest="category_slug", default="general", help="Slug de catégorie")
    p.add_argument("--subcategory",         default="", help="Sous-catégorie")
    p.add_argument("--limit",               type=int, default=None, help=f"Nbre de produits (défaut: 5 pour --create-comparison, {DEFAULT_BULK_LIMIT} pour --bulk-import)")
    p.add_argument("--dry-run",             action="store_true", help="Simuler sans écrire en base")
    p.add_argument("--force-download",      action="store_true", help="Re-télécharger le flux")
    p.add_argument("--feed-category",      default="", metavar="CAT", help="Filtrer par merchant_category du flux")
    p.add_argument("--min-price",           type=float, default=0.0, help="Prix minimum des produits sélectionnés")
    p.add_argument("--local-feed",          metavar="PATH", help="Utiliser un CSV local au lieu du téléchargement")
    p.add_argument("--yes",                 action="store_true", help="Confirmer --reset sans prompt")

    args = p.parse_args()

    # ── Charger la config du marchand et surcharger les constantes globales ──
    global RDC_PROGRAMME_ID, RDC_PARTNER_KEY, RDC_COUNTRY, AWIN_PUBLISHER_ID
    merchant_cfg = _load_merchant_config(args.merchant)
    if merchant_cfg and merchant_cfg.get("network") == "awin":
        RDC_PROGRAMME_ID = merchant_cfg.get("awin_programme_id", RDC_PROGRAMME_ID)
        RDC_PARTNER_KEY  = merchant_cfg["key"]
        RDC_COUNTRY      = merchant_cfg.get("country", "fr")
        # Publisher ID peut être surchargé par le champ dédié dans merchants.json
        if merchant_cfg.get("awin_publisher_id"):
            AWIN_PUBLISHER_ID = merchant_cfg["awin_publisher_id"]
    elif args.merchant != "rue-du-commerce" and not merchant_cfg:
        print(f"⚠   Marchand '{args.merchant}' introuvable dans config/merchants.json — config RDC utilisée par défaut.")

    # Résoudre la limite selon la commande
    effective_limit = args.limit if args.limit is not None else (
        DEFAULT_BULK_LIMIT if args.bulk_import else 5
    )

    local = args.local_feed
    if args.bulk_import:
        cmd_bulk_import(
            merchant_key=args.merchant, limit=effective_limit,
            dry_run=args.dry_run, force=args.force_download,
            local_path=local, category_filter=args.feed_category,
        )
    elif args.reset:
        cmd_reset(args.yes)
    elif args.discover:
        cmd_discover(args.discover, args.limit, args.force_download, local)
    elif args.list_categories:
        cmd_list_categories(args.force_download, local)
    elif args.create_comparison:
        if args.query is None or not args.slug or not args.title:
            p.error("--create-comparison requiert --query (peut être vide), --slug et --title")
        cmd_create_comparison(
            query=args.query, slug=args.slug, title=args.title,
            category_slug=args.category_slug, subcategory=args.subcategory,
            limit=effective_limit, dry_run=args.dry_run, force=args.force_download,
            local_path=local, feed_category=args.feed_category,
            min_price=args.min_price,
        )
    elif args.refresh_prices:
        cmd_refresh_prices(args.force_download, local)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
