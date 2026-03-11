#!/usr/bin/env python3
"""
import-awin-feed.py — Importe les flux produits Awin pour les marchands FR

Fonctionnement :
  1. Télécharge le flux CSV via l'API Awin (ou URL directe)
  2. Parse les colonnes : ean, name, price, currency, merchant_url, image_url, stock, deep_link
  3. Match les produits Supabase par EAN ou nom (fuzzy)
  4. Upsert affiliate_links avec les nouvelles données

Marchands supportés :
  - fnac        (Awin programme ID : 19024)
  - darty       (Awin programme ID : 12188)
  - boulanger   (Awin programme ID : 16285)
  - la-redoute  (Awin programme ID : 12181)
  - maison-du-monde (Awin programme ID : 15697)

Usage :
    python scripts/import-awin-feed.py                          # Tous les marchands
    python scripts/import-awin-feed.py --merchant fnac          # Un seul
    python scripts/import-awin-feed.py --merchant fnac --dry-run
    python scripts/import-awin-feed.py --discover               # Liste les produits matchés sans importer

Environment variables:
    AWIN_API_TOKEN          — Awin Publisher API token (compte → API Access)
    AWIN_PUBLISHER_ID       — Ton Publisher ID Awin
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

Note : quand tu reçois tes crédentials Awin, tu n'as PAS besoin de modifier ce script.
       Il suffit de remplir AWIN_API_TOKEN et AWIN_PUBLISHER_ID dans .env.
"""

import argparse
import csv
import io
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

AWIN_API_TOKEN = os.getenv("AWIN_API_TOKEN", "")
AWIN_PUBLISHER_ID = os.getenv("AWIN_PUBLISHER_ID", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Awin API endpoints
AWIN_FEED_API = "https://productdata.awin.com/datafeed/download/apikey/{api_token}/language/fr/fid/{feed_id}/columns/{columns}/format/csv/"
AWIN_PROGRAMME_API = "https://api.awin.com/publishers/{publisher_id}/programmes/{programme_id}/feeds"

# Merchant programme IDs on Awin FR
MERCHANTS: dict[str, dict] = {
    "fnac": {
        "label": "Fnac",
        "programme_id": "19024",
        "feed_id": None,   # Sera découvert via l'API Awin
        "country": "FR",
        "tracking_url_template": "https://www.awin1.com/cread.php?awinmid={programme_id}&awinaffid={publisher_id}&ued={url}",
    },
    "darty": {
        "label": "Darty",
        "programme_id": "12188",
        "feed_id": None,
        "country": "FR",
        "tracking_url_template": "https://www.awin1.com/cread.php?awinmid={programme_id}&awinaffid={publisher_id}&ued={url}",
    },
    "boulanger": {
        "label": "Boulanger",
        "programme_id": "16285",
        "feed_id": None,
        "country": "FR",
        "tracking_url_template": "https://www.awin1.com/cread.php?awinmid={programme_id}&awinaffid={publisher_id}&ued={url}",
    },
    "la-redoute": {
        "label": "La Redoute",
        "programme_id": "12181",
        "feed_id": None,
        "country": "FR",
        "tracking_url_template": "https://www.awin1.com/cread.php?awinmid={programme_id}&awinaffid={publisher_id}&ued={url}",
    },
    "maison-du-monde": {
        "label": "Maison du Monde",
        "programme_id": "15697",
        "feed_id": None,
        "country": "FR",
        "tracking_url_template": "https://www.awin1.com/cread.php?awinmid={programme_id}&awinaffid={publisher_id}&ued={url}",
    },
}

# Awin CSV columns to request
AWIN_COLUMNS = "aw_product_id,product_name,aw_image_url,merchant_product_id,ean,search_price,currency_symbol,merchant_deep_link,in_stock,last_updated"


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _sb_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def fetch_all_products() -> list[dict]:
    """Fetch all products from Supabase (id, name, ean, asin)."""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/products?select=id,name,ean,asin&limit=1000",
        headers=_sb_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def upsert_affiliate_link(product_id: int, partner_id: str, data: dict) -> None:
    """Upsert affiliate_links row."""
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/affiliate_links",
        headers={**_sb_headers(), "Prefer": "resolution=merge-duplicates"},
        json={
            "product_id": product_id,
            "partner_id": partner_id,
            "partner_label": data.get("label", ""),
            "url": data["url"],
            "price": data.get("price"),
            "currency": data.get("currency", "EUR"),
            "in_stock": data.get("in_stock", True),
            "image_url": data.get("image_url"),
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "paapi_enabled": False,
        },
        timeout=10,
    )
    resp.raise_for_status()


# ── Awin helpers ──────────────────────────────────────────────────────────────

def _discover_feed_id(merchant: dict) -> Optional[str]:
    """Discover Awin feed ID for a programme via the API."""
    if not AWIN_API_TOKEN or not AWIN_PUBLISHER_ID:
        return None
    try:
        url = AWIN_PROGRAMME_API.format(
            publisher_id=AWIN_PUBLISHER_ID,
            programme_id=merchant["programme_id"],
        )
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {AWIN_API_TOKEN}"},
            timeout=15,
        )
        if resp.status_code == 200:
            feeds = resp.json()
            if feeds:
                return str(feeds[0].get("id", ""))
    except Exception:
        pass
    return None


def download_awin_feed(merchant_key: str, merchant: dict) -> list[dict]:
    """Download and parse Awin CSV feed. Returns list of product dicts."""
    if not AWIN_API_TOKEN:
        print(f"  ⚠  AWIN_API_TOKEN absent — impossible de télécharger le flux {merchant['label']}")
        print(f"     Configure : export AWIN_API_TOKEN=xxx  (Awin → API Access)")
        return []

    feed_id = merchant.get("feed_id") or _discover_feed_id(merchant)
    if not feed_id:
        print(f"  ⚠  Feed ID introuvable pour {merchant['label']} (programme {merchant['programme_id']})")
        print(f"     Vérifie que tu es bien approuvé pour ce programme Awin.")
        return []

    url = AWIN_FEED_API.format(
        api_token=AWIN_API_TOKEN,
        feed_id=feed_id,
        columns=AWIN_COLUMNS,
    )
    print(f"  ⬇  Téléchargement flux {merchant['label']} …")
    resp = requests.get(url, timeout=120, stream=True)
    if resp.status_code == 401:
        print(f"  ✗ AWIN_API_TOKEN invalide ou expirée.")
        return []
    if resp.status_code == 403:
        print(f"  ✗ Non approuvé pour le programme {merchant['label']} (ID {merchant['programme_id']}).")
        return []
    resp.raise_for_status()

    content = resp.content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    print(f"     → {len(rows)} produits dans le flux")
    return rows


def _build_tracking_url(merchant: dict, raw_url: str) -> str:
    """Wrap raw product URL with Awin tracking template."""
    from urllib.parse import quote
    template = merchant["tracking_url_template"]
    return template.format(
        programme_id=merchant["programme_id"],
        publisher_id=AWIN_PUBLISHER_ID or "0",
        url=quote(raw_url, safe=""),
    )


# ── Matching logic ────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase, remove special chars, normalize spaces."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_matching_product(awin_row: dict, products: list[dict]) -> Optional[dict]:
    """
    Match Awin product row to a Supabase product.
    Priority: EAN exact match → ASIN match → name fuzzy match (tokens).
    """
    awin_ean = awin_row.get("ean", "").strip()
    awin_name_raw = awin_row.get("product_name", "")
    awin_name = _normalize(awin_name_raw)

    for product in products:
        # 1. EAN exact match
        if awin_ean and product.get("ean") and awin_ean == product["ean"]:
            return product

        # 2. Name fuzzy: check if all tokens of product name appear in Awin name
        if product.get("name"):
            prod_tokens = set(_normalize(product["name"]).split())
            if len(prod_tokens) >= 2 and prod_tokens.issubset(set(awin_name.split())):
                return product

    return None


def parse_price(price_str: str) -> Optional[float]:
    """Parse '299.99' or '299,99' to float."""
    try:
        return float(price_str.replace(",", ".").strip())
    except (ValueError, AttributeError):
        return None


# ── Core import ───────────────────────────────────────────────────────────────

def import_merchant_feed(merchant_key: str, dry_run: bool = False, discover_only: bool = False) -> dict:
    """Import a single merchant's Awin feed. Returns stats dict."""
    merchant = MERCHANTS[merchant_key]
    print(f"\n\033[1;34m{'[DRY RUN] ' if dry_run else ''}🏪 {merchant['label']}\033[0m")

    products = fetch_all_products()
    if not products:
        print("  ⚠  Aucun produit en base Supabase.")
        return {"merchant": merchant_key, "matched": 0, "updated": 0, "total_feed": 0}

    rows = download_awin_feed(merchant_key, merchant)
    if not rows:
        return {"merchant": merchant_key, "matched": 0, "updated": 0, "total_feed": 0}

    matched = 0
    updated = 0

    for row in rows:
        product = find_matching_product(row, products)
        if not product:
            continue

        matched += 1
        price = parse_price(row.get("search_price", ""))
        raw_url = row.get("merchant_deep_link", "").strip()
        tracking_url = _build_tracking_url(merchant, raw_url) if raw_url else ""
        in_stock = row.get("in_stock", "").lower() in ("1", "yes", "true", "in stock", "en stock")
        image_url = row.get("aw_image_url", "").strip() or None

        if discover_only:
            print(f"  ✓ Match : '{product['name']}' ← '{row.get('product_name', '')[:60]}' — {price} €")
            continue

        if not dry_run and tracking_url:
            try:
                upsert_affiliate_link(
                    product_id=product["id"],
                    partner_id=merchant_key,
                    data={
                        "label": merchant["label"],
                        "url": tracking_url,
                        "price": price,
                        "currency": "EUR",
                        "in_stock": in_stock,
                        "image_url": image_url,
                    },
                )
                updated += 1
            except Exception as e:
                print(f"  ✗ Erreur upsert {product['name']}: {e}")
        elif dry_run:
            print(f"  [DRY] {product['name']} — {price} € → {tracking_url[:80]}…")
            updated += 1

    if not discover_only:
        print(f"  → Matched: {matched} | Mis à jour: {updated} / {len(rows)} produits feed")

    return {"merchant": merchant_key, "matched": matched, "updated": updated, "total_feed": len(rows)}


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Importe les flux Awin pour AffiliCompare")
    parser.add_argument(
        "--merchant",
        choices=list(MERCHANTS.keys()) + ["all"],
        default="all",
        help="Marchand à importer (défaut: tous)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Simule sans écrire en base")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Affiche les produits matchés sans importer",
    )
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("\033[1;31m✗ SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis.\033[0m")
        sys.exit(1)

    merchants_to_process = list(MERCHANTS.keys()) if args.merchant == "all" else [args.merchant]

    print(f"\n\033[1;35m🏪 AffiliCompare — Import Awin Feeds\033[0m")
    print(f"   Marchands : {', '.join(merchants_to_process)}")
    print(f"   Mode      : {'DRY RUN' if args.dry_run else ('DISCOVER' if args.discover else 'LIVE')}")

    results = []
    for key in merchants_to_process:
        result = import_merchant_feed(key, dry_run=args.dry_run, discover_only=args.discover)
        results.append(result)
        if len(merchants_to_process) > 1:
            time.sleep(2)  # Polite delay between merchants

    # Summary
    print(f"\n\033[1;32m📊 Résumé :\033[0m")
    total_updated = 0
    for r in results:
        print(f"   {r['merchant']:20} matched={r['matched']:3}  updated={r['updated']:3}  feed={r['total_feed']:5}")
        total_updated += r["updated"]
    print(f"   {'TOTAL':20} updated={total_updated}")
    print()


if __name__ == "__main__":
    main()
