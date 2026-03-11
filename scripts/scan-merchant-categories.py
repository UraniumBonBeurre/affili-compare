#!/usr/bin/env python3
"""
scan-merchant-categories.py — Scanne les catégories disponibles dans les flux Awin
====================================================================================

Pour chaque marchand actif (config/merchants.json), lit le flux produit (cache ou
fichier local) et extrait toutes les valeurs uniques de merchant_category.

Génère / met à jour config/merchant-categories.json :
  {
    "rue-du-commerce": {
      "Informatique > Ordinateurs portables": true,
      "TV & Home Cinéma > Téléviseurs":       true,
      "Câbles & Accessoires":                 false   ← mis manuellement à false
    },
    "imou_fr": {
      "Cameras & Optics > Surveillance Cameras": true
    }
  }

Règles :
  • Les nouvelles catégories découvertes sont ajoutées avec true.
  • Les entrées existantes (y compris les false manuels) sont PRÉSERVÉES.
  • Trier les catégories alphabétiquement pour faciliter la lecture.

Usage :
    # Scanner tous les marchands dont le flux est déjà en cache
    python3 scripts/scan-merchant-categories.py

    # Fournir un flux local pour un marchand spécifique
    python3 scripts/scan-merchant-categories.py \\
        --feed imou_fr=/path/to/imou_feed.csv \\
        --feed rue-du-commerce=/path/to/rdc_feed.csv

    # Forcer le re-téléchargement des flux (requiert clés Awin)
    python3 scripts/scan-merchant-categories.py --force-download

    # N'afficher que le résumé, sans modifier le fichier
    python3 scripts/scan-merchant-categories.py --dry-run
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

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

ROOT = Path(__file__).parent.parent
CACHE_DIR          = ROOT / ".cache"
MERCHANTS_CFG      = ROOT / "config" / "merchants.json"
CATEGORIES_CFG     = ROOT / "config" / "merchant-categories.json"

AWIN_PRODUCTDATA_KEY = os.getenv("AWIN_PRODUCTDATA_KEY") or os.getenv("AWIN_API_TOKEN", "")
AWIN_PUBLISHER_ID    = os.getenv("AWIN_PUBLISHER_ID", "")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_merchants() -> list[dict]:
    if not MERCHANTS_CFG.exists():
        print(f"❌  {MERCHANTS_CFG} introuvable.")
        sys.exit(1)
    data = json.loads(MERCHANTS_CFG.read_text(encoding="utf-8"))
    return [m for m in data.get("merchants", []) if m.get("network") == "awin"]


def _cache_path_for(merchant: dict) -> Path:
    """Convention de nommage du cache : feed_{programme_id}.csv"""
    prog_id = merchant.get("awin_programme_id", merchant["key"])
    # Compatibilité avec le nom historique pour RDC
    rdc_legacy = CACHE_DIR / f"rdc_feed_{prog_id}.csv"
    if rdc_legacy.exists():
        return rdc_legacy
    return CACHE_DIR / f"feed_{prog_id}.csv"


def _download_feed(merchant: dict) -> Path | None:
    """Télécharge le flux via l'API ProductData Awin."""
    if not AWIN_PRODUCTDATA_KEY:
        return None
    prog_id = merchant.get("awin_programme_id", "")
    if not prog_id:
        return None

    FEED_COLUMNS = ",".join([
        "aw_product_id", "product_name", "brand_name",
        "aw_image_url", "aw_thumb_url",
        "ean", "search_price", "currency",
        "merchant_deep_link", "aw_deep_link",
        "in_stock", "last_updated",
        "category_name", "merchant_category",
    ])
    from urllib.parse import quote as urlquote
    import gzip as gzip_lib

    # Tenter la découverte automatique du feed_id
    feed_id = _discover_feed_id(prog_id)
    if not feed_id:
        return None

    CACHE_DIR.mkdir(exist_ok=True)
    out_path = CACHE_DIR / f"feed_{prog_id}.csv"
    gz_path  = CACHE_DIR / f"feed_{prog_id}.csv.gz"

    cols_enc = urlquote(FEED_COLUMNS, safe="")
    url = (
        f"https://productdata.awin.com/datafeed/download"
        f"/apikey/{AWIN_PRODUCTDATA_KEY}"
        f"/fid/{feed_id}/format/csv/language/fr"
        f"/delimiter/%2C/compression/gzip"
        f"/columns/{cols_enc}/"
    )
    print(f"    ⬇  Téléchargement flux {merchant['key']} (feed {feed_id})…")
    try:
        r = requests.get(url, timeout=300, stream=True, allow_redirects=True)
        if r.status_code not in (200, 206):
            print(f"    ⚠  HTTP {r.status_code} — flux {merchant['key']} ignoré")
            return None
        with open(gz_path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        with gzip_lib.open(gz_path, "rt", encoding="utf-8", errors="replace") as gz:
            out_path.write_text(gz.read(), encoding="utf-8")
        gz_path.unlink(missing_ok=True)
        return out_path
    except Exception as e:
        print(f"    ⚠  Erreur téléchargement : {e}")
        return None


def _discover_feed_id(programme_id: str) -> str | None:
    if not AWIN_PRODUCTDATA_KEY:
        return None
    import io
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


def _read_feed(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    # Certains flux ont des espaces dans les noms de colonnes — on les normalise
    if rows and any(k is not None and k != k.strip() for k in rows[0]):
        rows = [{(k.strip() if k else k): v for k, v in row.items()} for row in rows]
    return rows


def _get_category(row: dict) -> str:
    raw = (row.get("merchant_category") or row.get("category_name") or "").strip()
    # Nettoyer les guillemets parasites (certains flux mal échappés)
    return raw.strip('"').strip()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Scanner les catégories de tous les flux marchands")
    p.add_argument("--feed", action="append", metavar="KEY=PATH",
                   help="Flux local pour un marchand (ex: imou_fr=/path/feed.csv) — répétable")
    p.add_argument("--force-download", action="store_true",
                   help="Re-télécharger les flux (requiert AWIN_PRODUCTDATA_KEY)")
    p.add_argument("--dry-run", action="store_true",
                   help="Afficher uniquement, sans modifier merchant-categories.json")
    p.add_argument("--only", metavar="KEY",
                   help="Scanner uniquement ce marchand")
    args = p.parse_args()

    # Charger les flux locaux fournis en argument
    local_feeds: dict[str, Path] = {}
    for entry in (args.feed or []):
        if "=" not in entry:
            print(f"⚠  Format invalide --feed '{entry}' (attendu: KEY=PATH)")
            continue
        key, _, path_str = entry.partition("=")
        local_feeds[key.strip()] = Path(path_str.strip())

    merchants = _load_merchants()
    if args.only:
        merchants = [m for m in merchants if m["key"] == args.only]
        if not merchants:
            print(f"❌  Marchand '{args.only}' introuvable dans merchants.json")
            sys.exit(1)

    # Charger l'état actuel du fichier de catégories (pour préserver les false manuels)
    existing: dict[str, dict[str, bool]] = {}
    if CATEGORIES_CFG.exists():
        try:
            existing = json.loads(CATEGORIES_CFG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    result: dict[str, dict[str, bool]] = {}
    total_new = 0

    for merchant in merchants:
        key = merchant["key"]

        # Déterminer la source du flux
        feed_path: Path | None = None

        if key in local_feeds:
            feed_path = local_feeds[key]
            if not feed_path.exists():
                print(f"⚠  [{key}] Fichier introuvable : {feed_path}")
                continue
            print(f"📂  [{key}] Flux local : {feed_path.name}")
        else:
            cache = _cache_path_for(merchant)
            if cache.exists() and not args.force_download:
                import time
                age_h = (time.time() - cache.stat().st_mtime) / 3600
                print(f"📦  [{key}] Cache ({age_h:.0f}h) : {cache.name}")
                feed_path = cache
            elif args.force_download or not cache.exists():
                downloaded = _download_feed(merchant)
                if downloaded:
                    feed_path = downloaded
                else:
                    print(f"⚠  [{key}] Flux non disponible — ignoré")
                    continue

        # Lire le flux et extraire les catégories
        rows = _read_feed(feed_path)
        cats_found = sorted({_get_category(r) for r in rows if _get_category(r)})

        # Si le flux n'a pas de catégories, utiliser default_category du marchand
        default_cat = merchant.get("default_category", "").strip()
        if not cats_found and default_cat:
            print(f"   ℹ  Aucune catégorie dans le flux — utilisation de la catégorie par défaut : \"{default_cat}\"")
            cats_found = [default_cat]

        # Fusionner avec l'existant (préserve les false)
        prev = existing.get(key, {})
        merged: dict[str, bool] = {}
        new_cats = 0
        for cat in cats_found:
            if cat in prev:
                merged[cat] = prev[cat]  # préserve la valeur manuelle
            else:
                merged[cat] = True
                new_cats += 1

        result[key] = merged
        total_new += new_cats

        enabled  = sum(1 for v in merged.values() if v)
        disabled = len(merged) - enabled
        new_tag  = f"  (+{new_cats} nouvelles)" if new_cats else ""
        print(f"   → {len(merged)} catégories : {enabled} activées, {disabled} désactivées{new_tag}")
        for cat in cats_found[:6]:
            status = "✅" if merged[cat] else "❌"
            print(f"      {status}  {cat}")
        if len(cats_found) > 6:
            print(f"      … et {len(cats_found) - 6} autres")
        print()

    if not result:
        print("Aucun flux disponible à scanner.")
        return

    if args.dry_run:
        print(f"\n[DRY-RUN] {total_new} nouvelles catégories détectées — fichier non modifié.")
        return

    # Écrire le fichier de configuration
    CATEGORIES_CFG.parent.mkdir(exist_ok=True)
    # Trier les clés alphébétiquement pour chaque marchand
    output = {
        merchant_key: dict(sorted(cats.items()))
        for merchant_key, cats in sorted((existing | result).items())
    }
    CATEGORIES_CFG.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅  {CATEGORIES_CFG} mis à jour ({total_new} nouvelles catégories ajoutées)")
    print(f"\n   Édite ce fichier pour mettre des catégories à `false` avant l'import.")
    print(f"   Exemple : \"Câbles & Accessoires\": false")


if __name__ == "__main__":
    main()
