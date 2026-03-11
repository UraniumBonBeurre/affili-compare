#!/usr/bin/env python3
"""
enrich-amazon-links.py — Enrichit les produits avec des liens affiliés Amazon
==============================================================================

Pour chaque produit ayant un EAN dans la table products :
  1. Cherche l'ASIN Amazon correspondant via l'API gratuite UPCItemDB
     (https://www.upcitemdb.com/ — 100 req/jour en free tier)
  2. Si ASIN trouvé → amazon_url = https://www.amazon.fr/dp/{ASIN}?tag={TAG}
  3. Sinon            → amazon_url = https://www.amazon.fr/s?k={EAN}&tag={TAG}
     (lien affilié de recherche, aussi valide pour les commissions)

Deux colonnes sont mises à jour dans products :
  • amazon_asin   (text | null)
  • amazon_url    (text | null)

Prérequis DB :
  Appliquer supabase/migrations/20260310_amazon_fields.sql dans Supabase SQL Editor :
    ALTER TABLE products
      ADD COLUMN IF NOT EXISTS ean text,
      ADD COLUMN IF NOT EXISTS amazon_asin text,
      ADD COLUMN IF NOT EXISTS amazon_url text;

Usage :
    python3 scripts/enrich-amazon-links.py                   # Tous les produits avec EAN
    python3 scripts/enrich-amazon-links.py --limit 50        # Seulement 50 produits
    python3 scripts/enrich-amazon-links.py --dry-run         # Ne sauvegarde pas
    python3 scripts/enrich-amazon-links.py --category gaming # Filtrer par catégorie
    python3 scripts/enrich-amazon-links.py --force           # Re-enrichir même si amazon_url existe
    python3 scripts/enrich-amazon-links.py --backfill-ean    # Remplir ean depuis le CSV local avant d'enrichir
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("❌  pip install requests")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
_root = Path(__file__).resolve().parent.parent

def _load_env():
    env_path = _root / ".env.local"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

_load_env()

SUPABASE_URL  = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY  = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
AMAZON_TAG    = os.environ.get("AMAZON_ASSOCIATE_TAG_FR") or os.environ.get("AMAZON_ASSOCIATE_TAG", "afprod-21")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌  NEXT_PUBLIC_SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY manquant dans .env.local")
    sys.exit(1)

SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

# UPCItemDB free-tier rate limit: 100 req/day, max 6 req/min
UPCITEMDB_DELAY = 10   # seconds between calls (safe: 6 req/min = 1 req/10s)
UPCITEMDB_URL   = "https://api.upcitemdb.com/prod/trial/lookup"

# Cache persisted to disk to avoid re-querying UPCItemDB across runs
CACHE_FILE = _root / ".cache" / "ean_asin_cache.json"


# ── Supabase helpers ──────────────────────────────────────────────────────────
def sb_get(path: str, params: str = "") -> list:
    url = f"{SUPABASE_URL}/rest/v1/{path}{'?' + params if params else ''}"
    r = requests.get(url, headers=SB_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def sb_patch(table: str, record_id: str, data: dict) -> bool:
    headers = {**SB_HEADERS, "Prefer": "return=minimal"}
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{record_id}",
        headers=headers,
        json=data,
        timeout=30,
    )
    if r.status_code not in (200, 204):
        print(f"  ⚠️  PATCH {table}/{record_id}: HTTP {r.status_code} — {r.text[:100]}")
        return False
    return True


def sb_upsert_batch(table: str, records: list) -> bool:
    """Bulk upsert using Supabase merge-duplicates (matches on primary key 'id')."""
    headers = {**SB_HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"}
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=headers,
        json=records,
        timeout=60,
    )
    if r.status_code not in (200, 201, 204):
        print(f"  ⚠️  UPSERT {table}: HTTP {r.status_code} — {r.text[:120]}")
        return False
    return True


# ── EAN → ASIN lookup ─────────────────────────────────────────────────────────
def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


def lookup_asin(ean: str, cache: dict) -> str | None:
    """
    Retourne l'ASIN Amazon pour un EAN donné, ou None.
    Utilise le cache disque pour éviter de re-requêter UPCItemDB.
    """
    if ean in cache:
        return cache[ean]  # peut être None si déjà essayé sans succès

    try:
        r = requests.get(
            UPCITEMDB_URL,
            params={"upc": ean},
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if r.status_code == 429:
            print("  ⏳ UPCItemDB: rate limit (429) — pause 60s…")
            time.sleep(60)
            r = requests.get(UPCITEMDB_URL, params={"upc": ean},
                             headers={"Accept": "application/json"}, timeout=15)

        if r.status_code == 200:
            data = r.json()
            items = data.get("items") or []
            for item in items:
                asin = item.get("asin") or ""
                if asin and len(asin) == 10 and asin.startswith("B"):
                    cache[ean] = asin
                    return asin
    except Exception as e:
        print(f"  ⚠️  UPCItemDB erreur pour EAN {ean}: {e}")

    # Pas d'ASIN trouvé → mémoriser pour éviter de re-requêter
    cache[ean] = None
    return None


def make_amazon_url(ean: str, asin: str | None) -> str:
    """
    Construit le lien affilié Amazon.
    Avec ASIN : lien produit direct (meilleur pour les commissions).
    Sans ASIN  : lien recherche par EAN (toujours valide en affiliation).
    """
    if asin:
        return f"https://www.amazon.fr/dp/{asin}?tag={AMAZON_TAG}"
    # Lien de recherche : le client voit le produit en premier résultat si l'EAN est exact
    return f"https://www.amazon.fr/s?k={ean}&tag={AMAZON_TAG}"


# ── Backfill EAN depuis le CSV local ─────────────────────────────────────────
def backfill_ean_from_csv(dry_run: bool = False) -> int:
    """
    Parcourt le CSV local (.cache/rdc_feed_6901.csv ou similaire) et met à jour
    en masse les produits en DB qui ont un external_id correspondant mais pas encore d'EAN.
    Utilise des bulk upserts par lots de 500 pour ne pas spammer l'API.
    """
    cache_dir = _root / ".cache"
    csvs = list(cache_dir.glob("rdc_feed_*.csv"))
    if not csvs:
        print("⚠️  Aucun fichier .cache/rdc_feed_*.csv trouvé — backfill ignoré")
        return 0

    csv_path = sorted(csvs)[-1]
    print(f"📂 Backfill EAN depuis {csv_path.name}…")

    # Construire la map ext_id → ean depuis le CSV
    ext_to_ean: dict[str, str] = {}
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            ext_id = (row.get("aw_product_id") or "").strip()
            ean    = (row.get("ean") or "").strip()
            if ext_id and ean:
                ext_to_ean[ext_id] = ean

    if not ext_to_ean:
        print("  ⚠️  Aucun EAN dans le CSV")
        return 0

    print(f"  → {len(ext_to_ean):,} lignes CSV avec EAN")

    # Récupérer les produits sans EAN, paginés pour éviter des requêtes trop grosses
    matched: list[dict] = []
    page, page_size = 0, 1000
    while True:
        batch = sb_get(
            "products",
            f"select=id,external_id&ean=is.null&external_id=not.is.null"
            f"&limit={page_size}&offset={page * page_size}",
        )
        for p in batch:
            ext_id = p.get("external_id") or ""
            if ext_id in ext_to_ean:
                matched.append({"id": p["id"], "ean": ext_to_ean[ext_id]})
        if len(batch) < page_size:
            break
        page += 1

    print(f"  → {len(matched):,} produits à mettre à jour")
    if dry_run:
        print("  ℹ️  DRY-RUN : aucune écriture")
        return len(matched)

    # Bulk upsert par lots de 500
    updated = 0
    for i in range(0, len(matched), 500):
        chunk = matched[i:i + 500]
        if sb_upsert_batch("products", chunk):
            updated += len(chunk)
            print(f"  ✓ {updated}/{len(matched)} mis à jour…", end="\r")

    print(f"\n  ✓ {updated} produits enrichis avec leur EAN")
    return updated


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Enrichit les produits avec liens affiliés Amazon")
    parser.add_argument("--limit",     type=int, default=0,    help="Nombre max de produits (0=tous)")
    parser.add_argument("--offset",    type=int, default=0,    help="Décalage (pour reprendre)")
    parser.add_argument("--category",  default=None,           help="Filtrer par category_slug")
    parser.add_argument("--dry-run",   action="store_true",    help="N'écrit pas en DB")
    parser.add_argument("--force",     action="store_true",    help="Re-traite même si amazon_url existe")
    parser.add_argument("--backfill-ean", action="store_true", help="Remplir EAN depuis le CSV avant enrichissement")
    parser.add_argument("--no-api",    action="store_true",    help="Génère seulement les liens de recherche (pas d'appel UPCItemDB)")
    args = parser.parse_args()

    print(f"\n🔗 Enrichissement Amazon | TAG: {AMAZON_TAG}")
    if args.dry_run:
        print("   Mode DRY-RUN\n")

    # Vérifier que les colonnes existent
    try:
        sb_get("products", "select=id,ean,amazon_asin,amazon_url&limit=1")
    except Exception as e:
        print(f"\n❌  Les colonnes ean/amazon_asin/amazon_url n'existent pas encore.")
        print("   Appliquer la migration dans Supabase SQL Editor :")
        print()
        print("   ALTER TABLE products")
        print("     ADD COLUMN IF NOT EXISTS ean text,")
        print("     ADD COLUMN IF NOT EXISTS amazon_asin text,")
        print("     ADD COLUMN IF NOT EXISTS amazon_url text;")
        print()
        sys.exit(1)

    # Backfill EAN si demandé
    if args.backfill_ean:
        backfill_ean_from_csv(dry_run=args.dry_run)

    # Récupérer les produits à traiter
    filter_parts = ["ean=not.is.null"]  # doit avoir un EAN
    if not args.force:
        filter_parts.append("amazon_url=is.null")  # pas encore enrichi
    if args.category:
        filter_parts.append(f"category_slug=eq.{args.category}")

    params = ("select=id,name,brand,ean,amazon_asin,amazon_url"
              f"&{'&'.join(filter_parts)}"
              "&order=created_at.asc"
              f"&limit={args.limit if args.limit else 10000}"
              f"&offset={args.offset}")

    products = sb_get("products", params)
    total = len(products)
    print(f"📦 {total} produit(s) à traiter\n")

    if total == 0:
        print("✅ Rien à faire.")
        return

    cache = load_cache()
    ok = skipped = errors = 0

    for i, p in enumerate(products):
        ean  = p["ean"]
        name = p.get("name", "")[:50]
        pid  = p["id"]

        print(f"  [{i+1}/{total}] {name} | EAN: {ean}")

        # Lookup ASIN (cache first, then UPCItemDB sauf en dry-run ou --no-api)
        asin = cache.get(ean)
        if asin is None and not args.no_api and not args.dry_run:
            asin = lookup_asin(ean, cache)
            time.sleep(UPCITEMDB_DELAY)  # respect rate limit

        amazon_url = make_amazon_url(ean, asin)
        link_type  = f"dp/{asin}" if asin else f"search/{ean}"
        print(f"         → ASIN: {asin or '—'} | {link_type}")

        if not args.dry_run:
            data: dict = {"amazon_url": amazon_url}
            if asin:
                data["amazon_asin"] = asin
            if sb_patch("products", pid, data):
                ok += 1
            else:
                errors += 1
        else:
            ok += 1

        # Save cache periodically
        if (i + 1) % 20 == 0:
            save_cache(cache)

    save_cache(cache)

    print(f"\n{'─'*50}")
    print(f"✅ {ok}/{total} enrichis — ASIN trouvés: {sum(1 for v in cache.values() if v)}/{len(cache)}")
    if errors:
        print(f"❌ {errors} erreurs DB")
    print(f"💾 Cache: {CACHE_FILE}\n")


if __name__ == "__main__":
    main()
