#!/usr/bin/env python3
"""
show_and_set_merchants_categories.py — Gestion des catégories marchands Awin
=============================================================================

Scanne les flux produit Awin et génère/met à jour config/merchant_categories.json.
Les catégories découvertes sont ajoutées avec true, les false manuels sont préservés.

Usage :
    python3 scripts/show_and_set_merchants_categories.py
    python3 scripts/show_and_set_merchants_categories.py --force-download
    python3 scripts/show_and_set_merchants_categories.py --only imou_fr
    python3 scripts/show_and_set_merchants_categories.py --feed imou_fr=/path/feed.csv
    python3 scripts/show_and_set_merchants_categories.py --dry-run
"""

import argparse
import csv
import gzip as gzip_lib
import io
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote as urlquote

import requests

from settings import (
    ROOT, AWIN_API_TOKEN, AWIN_PUBLISHER_ID, AWIN_PRODUCTDATA_KEY,
    CACHE_DIR, MERCHANT_CATEGORIES_PATH,
)

MERCHANTS_CFG = ROOT / "config" / "merchants.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_awin_merchants() -> list[dict]:
    if not MERCHANTS_CFG.exists():
        print(f"❌  {MERCHANTS_CFG} introuvable")
        sys.exit(1)
    data = json.loads(MERCHANTS_CFG.read_text(encoding="utf-8"))
    return [m for m in data.get("merchants", []) if m.get("network") == "awin"]


def _cache_path_for(merchant: dict) -> Path:
    prog_id = merchant.get("awin_programme_id", merchant["key"])
    rdc_legacy = CACHE_DIR / f"rdc_feed_{prog_id}.csv"
    if rdc_legacy.exists():
        return rdc_legacy
    return CACHE_DIR / f"feed_{prog_id}.csv"


def _discover_feed_id(programme_id: str) -> str | None:
    if not AWIN_PRODUCTDATA_KEY:
        return None
    url = f"https://legacydatafeeds.awin.com/datafeed/list/apikey/{AWIN_PRODUCTDATA_KEY}/format/csv/"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            return None
        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            adv_id = row.get("Advertiser ID", "").strip().strip('"')
            if adv_id == programme_id:
                return row.get("Feed ID", "").strip().strip('"')
    except Exception:
        pass
    return None


def _download_feed(merchant: dict) -> Path | None:
    if not AWIN_PRODUCTDATA_KEY:
        return None
    prog_id = merchant.get("awin_programme_id", "")
    if not prog_id:
        return None

    FEED_COLUMNS = ",".join([
        "aw_product_id", "product_name", "brand_name",
        "aw_image_url", "aw_thumb_url", "ean", "search_price", "currency",
        "merchant_deep_link", "aw_deep_link",
        "in_stock", "last_updated", "category_name", "merchant_category",
    ])
    feed_id = _discover_feed_id(prog_id)
    if not feed_id:
        return None

    CACHE_DIR.mkdir(exist_ok=True)
    out_path = CACHE_DIR / f"feed_{prog_id}.csv"
    gz_path = CACHE_DIR / f"feed_{prog_id}.csv.gz"

    cols_enc = urlquote(FEED_COLUMNS, safe="")
    url = (
        f"https://productdata.awin.com/datafeed/download"
        f"/apikey/{AWIN_PRODUCTDATA_KEY}/fid/{feed_id}/format/csv/language/fr"
        f"/delimiter/%2C/compression/gzip/columns/{cols_enc}/"
    )
    print(f"    ⬇  Téléchargement flux {merchant['key']} (feed {feed_id})…")
    try:
        r = requests.get(url, timeout=300, stream=True, allow_redirects=True)
        if r.status_code not in (200, 206):
            print(f"    ⚠  HTTP {r.status_code}")
            return None
        with open(gz_path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        with gzip_lib.open(gz_path, "rt", encoding="utf-8", errors="replace") as gz:
            out_path.write_text(gz.read(), encoding="utf-8")
        gz_path.unlink(missing_ok=True)
        return out_path
    except Exception as e:
        print(f"    ⚠  Erreur: {e}")
        return None


def _read_feed(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if rows and any(k is not None and k != k.strip() for k in rows[0]):
        rows = [{(k.strip() if k else k): v for k, v in row.items()} for row in rows]
    return rows


def _get_category(row: dict) -> str:
    raw = (row.get("merchant_category") or row.get("category_name") or "").strip()
    return raw.strip('"').strip()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Scanner les catégories marchands Awin")
    p.add_argument("--feed", action="append", metavar="KEY=PATH",
                   help="Flux local (KEY=PATH) — répétable")
    p.add_argument("--force-download", action="store_true",
                   help="Re-télécharger les flux")
    p.add_argument("--dry-run", action="store_true",
                   help="Afficher sans modifier le fichier")
    p.add_argument("--only", metavar="KEY",
                   help="Scanner un seul marchand")
    args = p.parse_args()

    local_feeds: dict[str, Path] = {}
    for entry in (args.feed or []):
        if "=" not in entry:
            print(f"⚠  Format invalide: '{entry}' (attendu: KEY=PATH)")
            continue
        key, _, path_str = entry.partition("=")
        local_feeds[key.strip()] = Path(path_str.strip())

    merchants = _load_awin_merchants()
    if args.only:
        merchants = [m for m in merchants if m["key"] == args.only]
        if not merchants:
            print(f"❌ Marchand '{args.only}' introuvable")
            sys.exit(1)

    # État actuel
    existing: dict[str, dict[str, bool]] = {}
    if MERCHANT_CATEGORIES_PATH.exists():
        try:
            existing = json.loads(MERCHANT_CATEGORIES_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    result: dict[str, dict[str, bool]] = {}
    total_new = 0

    for merchant in merchants:
        key = merchant["key"]
        feed_path: Path | None = None

        if key in local_feeds:
            feed_path = local_feeds[key]
            if not feed_path.exists():
                print(f"⚠  [{key}] Fichier introuvable: {feed_path}")
                continue
            print(f"📂  [{key}] Flux local: {feed_path.name}")
        else:
            cache = _cache_path_for(merchant)
            if cache.exists() and not args.force_download:
                age_h = (time.time() - cache.stat().st_mtime) / 3600
                print(f"📦  [{key}] Cache ({age_h:.0f}h): {cache.name}")
                feed_path = cache
            else:
                downloaded = _download_feed(merchant)
                if downloaded:
                    feed_path = downloaded
                else:
                    print(f"⚠  [{key}] Flux non disponible")
                    continue

        rows = _read_feed(feed_path)
        cats_found = sorted({_get_category(r) for r in rows if _get_category(r)})

        default_cat = merchant.get("default_category", "").strip()
        if not cats_found and default_cat:
            print(f"   ℹ  Catégorie par défaut: \"{default_cat}\"")
            cats_found = [default_cat]

        prev = existing.get(key, {})
        merged: dict[str, bool] = {}
        new_cats = 0
        for cat in cats_found:
            if cat in prev:
                merged[cat] = prev[cat]
            else:
                merged[cat] = True
                new_cats += 1

        result[key] = merged
        total_new += new_cats

        enabled = sum(1 for v in merged.values() if v)
        disabled = len(merged) - enabled
        new_tag = f"  (+{new_cats} nouvelles)" if new_cats else ""
        print(f"   → {len(merged)} catégories: {enabled} activées, {disabled} désactivées{new_tag}")
        for cat in cats_found[:6]:
            status = "✅" if merged[cat] else "❌"
            print(f"      {status}  {cat}")
        if len(cats_found) > 6:
            print(f"      … et {len(cats_found) - 6} autres")
        print()

    if not result:
        print("Aucun flux disponible.")
        return

    if args.dry_run:
        print(f"\n[DRY-RUN] {total_new} nouvelles catégories — fichier non modifié.")
        return

    MERCHANT_CATEGORIES_PATH.parent.mkdir(exist_ok=True)
    output = {
        mk: dict(sorted(cats.items()))
        for mk, cats in sorted((existing | result).items())
    }
    MERCHANT_CATEGORIES_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"✅  {MERCHANT_CATEGORIES_PATH.name} mis à jour ({total_new} nouvelles catégories)")
    print(f"\n   Édite ce fichier pour mettre des catégories à false avant l'import.")


if __name__ == "__main__":
    main()
