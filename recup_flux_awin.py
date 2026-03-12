#!/usr/bin/env python3
"""
recup_flux_awin.py — Import produits depuis les flux Awin vers Supabase
========================================================================

Deux modes :
  --mode reset_and_fill N   Vide la table products et importe N produits par marchand actif
  --mode update             Import incrémental (seulement les nouveaux produits)

Utilise config/merchant_categories.json pour filtrer les catégories (false = exclu).
Utilise config/merchants.json pour la liste des marchands Awin actifs.

Usage :
    # Import incrémental (défaut 500 nouveaux produits par marchand)
    python3 scripts/recup_flux_awin.py --mode update

    # Import incrémental limité
    python3 scripts/recup_flux_awin.py --mode update --limit 100

    # Reset complet et remplissage avec 2000 produits par marchand
    python3 scripts/recup_flux_awin.py --mode reset_and_fill 2000

    # Un seul marchand
    python3 scripts/recup_flux_awin.py --mode update --merchant rue-du-commerce

    # Dry run
    python3 scripts/recup_flux_awin.py --mode update --dry-run
"""

import argparse
import csv
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from settings import (
    ROOT, SUPABASE_URL, SUPABASE_KEY, AWIN_API_TOKEN,
    AWIN_PUBLISHER_ID, AWIN_PRODUCTDATA_KEY, CACHE_DIR,
    MERCHANT_CATEGORIES_PATH, sb_headers, check_supabase,
)

# ── Colonnes du flux Awin ────────────────────────────────────────────────────
FEED_COLUMNS = ",".join([
    "aw_product_id", "product_name", "brand_name",
    "aw_image_url", "aw_thumb_url",
    "ean", "search_price", "currency",
    "merchant_deep_link", "aw_deep_link",
    "in_stock", "stock_quantity", "last_updated",
    "category_name", "description", "delivery_cost",
    "merchant_category", "average_rating", "reviews",
])

MERCHANTS_CONFIG_PATH = ROOT / "src" / "config" / "merchants.json"
DEFAULT_BULK_LIMIT = 500


# ══════════════════════════════════════════════════════════════════════════════
# MERCHANTS
# ══════════════════════════════════════════════════════════════════════════════

def _load_awin_merchants(only_key: str = None) -> list[dict]:
    """Charge les marchands actifs du réseau Awin depuis merchants.json."""
    if not MERCHANTS_CONFIG_PATH.exists():
        print(f"❌  {MERCHANTS_CONFIG_PATH} introuvable.")
        sys.exit(1)
    data = json.loads(MERCHANTS_CONFIG_PATH.read_text(encoding="utf-8"))
    merchants = [
        m for m in data.get("merchants", [])
        if m.get("network") == "awin" and m.get("active", False)
    ]
    if only_key:
        merchants = [m for m in merchants if m["key"] == only_key]
        if not merchants:
            print(f"❌  Marchand '{only_key}' introuvable ou inactif dans merchants.json")
            sys.exit(1)
    return merchants


# ══════════════════════════════════════════════════════════════════════════════
# FEED DOWNLOAD
# ══════════════════════════════════════════════════════════════════════════════

def _discover_feed_id(programme_id: str) -> tuple[str, str] | tuple[None, None]:
    """Retourne (feed_id, download_url) depuis la liste Awin, ou (None, None)."""
    if not AWIN_PRODUCTDATA_KEY:
        return None, None
    url = f"https://legacydatafeeds.awin.com/datafeed/list/apikey/{AWIN_PRODUCTDATA_KEY}/format/csv/"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            return None, None
        reader = csv.DictReader(io.StringIO(resp.text))
        candidates = []
        for row in reader:
            adv_id = row.get("Advertiser ID", "").strip().strip('"')
            if adv_id == programme_id:
                fid = row.get("Feed ID", "").strip().strip('"')
                name = row.get("Feed Name", "").strip().strip('"')
                nprods = int(row.get("No of products", "0").strip().strip('"') or 0)
                dl_url = row.get("URL", "").strip().strip('"')
                candidates.append((fid, name, nprods, dl_url))
        if not candidates:
            return None, None
        # Préfère le plus petit flux (produits en propre = plus qualitatif)
        candidates.sort(key=lambda x: x[2])
        fid, name, n, dl_url = candidates[0]
        print(f"  🔍  Feed ID découvert : {fid} ({name}, {n:,} produits)")
        return fid, dl_url
    except Exception:
        return None, None


def _cache_path_for(merchant: dict) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    prog_id = merchant.get("awin_programme_id", merchant["key"])
    legacy = CACHE_DIR / f"rdc_feed_{prog_id}.csv"
    if legacy.exists():
        return legacy
    return CACHE_DIR / f"feed_{prog_id}.csv"


def _download_feed(merchant: dict) -> Path | None:
    if not AWIN_PRODUCTDATA_KEY:
        return None
    prog_id = merchant.get("awin_programme_id", "")
    if not prog_id:
        return None

    feed_id, feed_url = _discover_feed_id(prog_id)
    if not feed_id:
        return None

    CACHE_DIR.mkdir(exist_ok=True)
    out_path = CACHE_DIR / f"feed_{prog_id}.csv"
    gz_path = CACHE_DIR / f"feed_{prog_id}.csv.gz"

    # Utilise l'URL exacte fournie par Awin (bonne langue + colonnes supportées)
    url = feed_url if feed_url else (
        f"https://productdata.awin.com/datafeed/download"
        f"/apikey/{AWIN_PRODUCTDATA_KEY}"
        f"/fid/{feed_id}/format/csv/language/en"
        f"/delimiter/%2C/compression/gzip"
        f"/columns/{quote(','.join(FEED_COLUMNS), safe='')}/"
    )

    print(f"  ⬇  Téléchargement flux {merchant['key']} (feed {feed_id})…")
    try:
        import gzip as gzip_lib
        r = requests.get(url, timeout=300, stream=True, allow_redirects=True)
        if r.status_code not in (200, 206):
            print(f"  ⚠  HTTP {r.status_code} — flux {merchant['key']} ignoré")
            return None
        with open(gz_path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        with gzip_lib.open(gz_path, "rt", encoding="utf-8", errors="replace") as gz:
            out_path.write_text(gz.read(), encoding="utf-8")
        gz_path.unlink(missing_ok=True)
        size_mb = out_path.stat().st_size / 1024 / 1024
        print(f"  ✅  Flux mis en cache : {out_path} ({size_mb:.1f} Mo)")
        return out_path
    except Exception as e:
        print(f"  ⚠  Erreur téléchargement : {e}")
        return None


def load_feed(merchant: dict, force_download: bool = False) -> list[dict]:
    """Charge le flux depuis le cache (< 6h) ou le télécharge."""
    cache = _cache_path_for(merchant)

    if not force_download and cache.exists():
        age_h = (time.time() - cache.stat().st_mtime) / 3600
        if age_h < 6:
            print(f"  📦  Cache flux ({age_h:.1f}h) — {cache.name}")
            with open(cache, encoding="utf-8", errors="replace") as f:
                rows = list(csv.DictReader(f))
            print(f"  → {len(rows):,} produits\n")
            return rows

    downloaded = _download_feed(merchant)
    if not downloaded:
        if cache.exists():
            print(f"  ⚠  Téléchargement échoué, utilisation du cache existant")
            with open(cache, encoding="utf-8", errors="replace") as f:
                rows = list(csv.DictReader(f))
            print(f"  → {len(rows):,} produits\n")
            return rows
        print(f"  ❌  Flux non disponible pour {merchant['key']}")
        return []

    with open(downloaded, encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
    print(f"  → {len(rows):,} produits\n")
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_category(row: dict) -> str:
    return row.get("merchant_category") or row.get("category_name") or "Divers"


def _parse_price(price_str: str) -> float | None:
    try:
        return round(float(price_str.replace(",", ".").strip()), 2)
    except (ValueError, AttributeError):
        return None


def _is_in_stock(row: dict) -> bool:
    val = (row.get("in_stock") or "").lower().strip()
    return val in ("1", "yes", "true", "en stock", "in stock")


def _tracking_url(row: dict, merchant: dict) -> str:
    aw = (row.get("aw_deep_link") or "").strip()
    if aw:
        return aw
    raw = (row.get("merchant_deep_link") or "").strip()
    if raw:
        prog_id = merchant.get("awin_programme_id", "")
        return (
            f"https://www.awin1.com/cread.php"
            f"?awinmid={prog_id}&awinaffid={AWIN_PUBLISHER_ID}"
            f"&ued={quote(raw, safe='')}"
        )
    return ""


def _infer_category_slug(merchant_cat: str) -> str:
    mc = merchant_cat.lower()
    if any(w in mc for w in ["tv", "télé", "hifi", "home cinéma", "enceinte", "barre de son"]):
        return "tv-hifi"
    if any(w in mc for w in ["jeux vidéo", "gaming", "console", "manette"]):
        return "gaming"
    if any(w in mc for w in ["informatique", "ordinateur", "laptop", "portable", "imprimante"]):
        return "informatique"
    if any(w in mc for w in ["smartphone", "téléphone", "mobile"]):
        return "smartphone"
    if any(w in mc for w in ["photo", "caméra", "vidéo"]):
        return "photo-video"
    if any(w in mc for w in ["électroménager", "cuisine", "réfrigér", "lave-", "aspirateur"]):
        return "electromenager"
    if any(w in mc for w in ["sécurité", "caméra ip", "surveillance", "alarme"]):
        return "securite"
    return "divers"


def _load_category_exclusions(merchant_key: str) -> set[str]:
    """Charge les catégories exclues (false) depuis merchant_categories.json."""
    if not MERCHANT_CATEGORIES_PATH.exists():
        return set()
    try:
        data = json.loads(MERCHANT_CATEGORIES_PATH.read_text(encoding="utf-8"))
        merchant_cats = data.get(merchant_key, {})
        return {k for k, v in merchant_cats.items() if v is False}
    except (json.JSONDecodeError, OSError):
        return set()


def _normalize_row_keys(rows: list[dict]) -> list[dict]:
    """Certains flux ont des espaces dans les noms de colonnes."""
    if rows and any(k is not None and k != k.strip() for k in rows[0]):
        return [{(k.strip() if k else k): v for k, v in row.items()} for row in rows]
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# SUPABASE
# ══════════════════════════════════════════════════════════════════════════════

def _build_payload(row: dict, merchant: dict) -> dict | None:
    """Construit le dict produit depuis une ligne de flux. Retourne None si invalide."""
    ext_id = (row.get("aw_product_id") or "").strip()
    name = (row.get("product_name") or "").strip()
    if not ext_id or not name:
        return None

    brand = (row.get("brand_name") or "").strip()
    image = (row.get("aw_image_url") or row.get("aw_thumb_url") or "").strip()
    ean = (row.get("ean") or "").strip() or None
    price = _parse_price(row.get("search_price", ""))
    in_stock = _is_in_stock(row)
    aff_url = _tracking_url(row, merchant)
    category_slug = _infer_category_slug(_get_category(row))
    merchant_category = _get_category(row)

    raw_rating = (row.get("average_rating") or "").strip()
    try:
        rating = float(raw_rating) if raw_rating else None
        if rating is not None:
            rating = round(min(5.0, max(0.0, rating)), 2)
    except ValueError:
        rating = None

    try:
        review_count = int(float(row.get("reviews") or "0"))
    except (ValueError, TypeError):
        review_count = 0

    return {
        "name": name[:200],
        "brand": (brand or "—")[:100],
        "image_url": image or None,
        "external_id": ext_id,
        "ean": ean,
        "price": price,
        "currency": "EUR",
        "rating": rating,
        "review_count": review_count,
        "category_slug": category_slug,
        "merchant_category": merchant_category,
        "merchant_key": merchant["key"],
        "affiliate_url": aff_url,
        "in_stock": in_stock,
        "active": True,
    }


BATCH_SIZE = 500


def _sb_batch_insert(payloads: list[dict], dry_run: bool = False) -> int:
    """Insère une liste de produits en batch. Retourne le nombre de produits envoyés."""
    if not payloads:
        return 0
    if dry_run:
        for p in payloads:
            print(f"  [DRY] {p['name'][:72]}  ({p.get('price') or 0:.2f}€)")
        return len(payloads)

    total = 0
    for i in range(0, len(payloads), BATCH_SIZE):
        chunk = payloads[i:i + BATCH_SIZE]
        try:
            r = requests.post(
                f"{SUPABASE_URL}/rest/v1/products",
                headers=sb_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                json=chunk,
                timeout=60,
            )
            r.raise_for_status()
            total += len(chunk)
            print(f"   … {total} produits importés")
        except Exception as e:
            print(f"  ⚠  Erreur batch {i}–{i+len(chunk)} : {e}")
    return total


# ══════════════════════════════════════════════════════════════════════════════
# MODE : UPDATE (incrémental)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_update(merchant: dict, limit: int, dry_run: bool, force_download: bool):
    """Import incrémental : insère seulement les nouveaux produits."""
    rows = load_feed(merchant, force_download)
    if not rows:
        return

    rows = _normalize_row_keys(rows)

    # Injecter catégorie par défaut si le flux n'en a pas
    default_cat = (merchant.get("default_category") or "").strip()
    if default_cat:
        no_cat = sum(1 for r in rows if not _get_category(r).strip())
        if no_cat:
            for r in rows:
                if not _get_category(r).strip():
                    r["merchant_category"] = default_cat
            print(f"   ℹ  Catégorie par défaut \"{default_cat}\" injectée sur {no_cat:,} produits")

    # Trier par last_updated DESC
    def _parse_dt(s: str):
        try:
            return datetime.fromisoformat(s.strip().replace(" ", "T"))
        except Exception:
            return datetime.min

    rows.sort(key=lambda r: _parse_dt(r.get("last_updated", "")), reverse=True)

    # Exclure les catégories désactivées
    excluded = _load_category_exclusions(merchant["key"])
    if excluded:
        before = len(rows)
        rows = [r for r in rows if _get_category(r) not in excluded]
        print(f"   Catégories exclues: {len(excluded)}  ({before - len(rows):,} produits filtrés)")

    # Identifier les produits déjà en base
    known_ids: set = set()
    if not dry_run:
        check_supabase()
        try:
            res = requests.get(
                f"{SUPABASE_URL}/rest/v1/products?select=external_id"
                f"&external_id=not.is.null&merchant_key=eq.{merchant['key']}",
                headers=sb_headers(), timeout=30,
            )
            res.raise_for_status()
            known_ids = {r["external_id"] for r in res.json() if r.get("external_id")}
        except Exception:
            pass

    new_rows = [r for r in rows if (r.get("aw_product_id") or "").strip() not in known_ids]

    print(f"{'[DRY-RUN] ' if dry_run else ''}📦  Import incrémental — {merchant['key']}")
    print(f"   Flux total   : {len(rows):>8,} produits")
    print(f"   Déjà en base : {len(rows) - len(new_rows):>8,}")
    print(f"   Nouveaux     : {len(new_rows):>8,}")
    print(f"   Ce run       : {min(limit, len(new_rows)):>8,}")
    print()

    payloads = [p for row in new_rows[:limit] if (p := _build_payload(row, merchant))]
    if dry_run:
        print(f"  [DRY] {len(payloads)} produits à insérer")
        _sb_batch_insert(payloads, dry_run=True)
    else:
        imported = _sb_batch_insert(payloads)
        print(f"\n✅  {imported} produits importés pour {merchant['key']}")
        return

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}✅  Import terminé pour {merchant['key']}")


# ══════════════════════════════════════════════════════════════════════════════
# MODE : RESET_AND_FILL
# ══════════════════════════════════════════════════════════════════════════════

def cmd_reset_and_fill(merchant: dict, count: int, dry_run: bool, force_download: bool):
    """Vide les produits du marchand et en importe count."""
    rows = load_feed(merchant, force_download)
    if not rows:
        return

    rows = _normalize_row_keys(rows)

    # Injecter catégorie par défaut
    default_cat = (merchant.get("default_category") or "").strip()
    if default_cat:
        for r in rows:
            if not _get_category(r).strip():
                r["merchant_category"] = default_cat

    # Exclure les catégories désactivées
    excluded = _load_category_exclusions(merchant["key"])
    if excluded:
        rows = [r for r in rows if _get_category(r) not in excluded]

    print(f"{'[DRY-RUN] ' if dry_run else ''}🗑️  Reset & Fill — {merchant['key']}")
    print(f"   Flux disponible : {len(rows):,} produits")
    print(f"   À importer      : {min(count, len(rows)):,}")

    if not dry_run:
        check_supabase()
        # Supprimer les produits existants de ce marchand
        try:
            r = requests.delete(
                f"{SUPABASE_URL}/rest/v1/products?merchant_key=eq.{merchant['key']}",
                headers=sb_headers({"Prefer": "return=minimal"}),
                timeout=30,
            )
            r.raise_for_status()
            print(f"   ✅  Produits {merchant['key']} supprimés de la base")
        except Exception as e:
            print(f"   ⚠  Erreur suppression : {e}")
            return

    payloads = [p for row in rows[:count] if (p := _build_payload(row, merchant))]
    imported = _sb_batch_insert(payloads, dry_run)
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}✅  {imported} produits importés pour {merchant['key']}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Import produits depuis les flux Awin → Supabase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", required=True, choices=["update", "reset_and_fill"],
                        help="Mode d'import : update (incrémental) ou reset_and_fill (vide + remplit)")
    parser.add_argument("--count", type=int, default=None,
                        help="Nombre de produits à importer (pour reset_and_fill)")
    parser.add_argument("--limit", type=int, default=DEFAULT_BULK_LIMIT,
                        help=f"Limite de produits par run pour update (défaut: {DEFAULT_BULK_LIMIT})")
    parser.add_argument("--merchant", default=None, metavar="KEY",
                        help="Marchand spécifique (défaut: tous les actifs)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simuler sans écrire en base")
    parser.add_argument("--force-download", action="store_true",
                        help="Re-télécharger le flux même si le cache est récent")
    args = parser.parse_args()

    merchants = _load_awin_merchants(args.merchant)
    if not merchants:
        print("❌  Aucun marchand Awin actif trouvé dans merchants.json")
        sys.exit(1)

    print(f"\n{'═'*62}")
    print(f"  📦  recup_flux_awin.py — Mode: {args.mode}")
    print(f"  Marchands : {', '.join(m['key'] for m in merchants)}")
    if args.dry_run:
        print("  Mode DRY-RUN")
    print(f"{'═'*62}\n")

    for merchant in merchants:
        if args.mode == "update":
            cmd_update(merchant, args.limit, args.dry_run, args.force_download)
        elif args.mode == "reset_and_fill":
            count = args.count or 500
            cmd_reset_and_fill(merchant, count, args.dry_run, args.force_download)
        print()


if __name__ == "__main__":
    main()
