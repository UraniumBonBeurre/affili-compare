#!/usr/bin/env python3
"""
sync-products.py — Synchronisation catalogue produits Awin <-> Supabase
======================================================================

Deux modes principaux :

  --first-import
      Import initial des N produits les plus populaires par marchand.
      Classement configurable dans config/update_database_config.json.

  --update
      Diff incremental pour chaque marchand :
        * Nouveaux produits dans le flux -> INSERT
        * Produits absents du flux      -> active = false  (soft-delete)
        * Produits existants modifies   -> UPDATE prix, stock, image...

Performance :
  * Batch upsert de BATCH_SIZE lignes par appel (~5 appels pour 1000 produits).
  * Prix / stock / lien affilie stockes directement sur la ligne `products`
    -> plus de jointure affiliate_links necessaire pour les imports bulk.

Commandes :

    python3 scripts/sync-products.py --first-import
    python3 scripts/sync-products.py --update
    python3 scripts/sync-products.py --reset --yes
    python3 scripts/sync-products.py --first-import --dry-run
    python3 scripts/sync-products.py --first-import --merchant imou_fr \
        --feed "imou_fr=/path/feed.csv"
"""

import argparse
import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env.local")
except ImportError:
    pass

try:
    from supabase import create_client, Client
except ImportError:
    print("pip install supabase python-dotenv")
    sys.exit(1)

# Config paths

ROOT           = Path(__file__).parent.parent
CACHE_DIR      = ROOT / ".cache"
MERCHANTS_CFG  = ROOT / "config" / "merchants.json"
CAT_FILTER_CFG = ROOT / "config" / "merchant-categories.json"
DB_CFG_PATH    = ROOT / "config" / "update_database_config.json"

BATCH_SIZE = 250  # lignes par appel Supabase upsert

# Credentials

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

_sb_client: Optional[Client] = None


def _sb() -> Client:
    global _sb_client
    if _sb_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            print("SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis dans .env.local")
            sys.exit(1)
        _sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sb_client


# Config

def _load_merchants() -> list:
    return json.loads(MERCHANTS_CFG.read_text(encoding="utf-8")).get("merchants", [])


def _db_cfg(key: str) -> dict:
    if not DB_CFG_PATH.exists():
        return {}
    return json.loads(DB_CFG_PATH.read_text(encoding="utf-8")).get(key, {})


def _excluded_categories(key: str) -> set:
    """Retourne les categories mises a false dans merchant-categories.json."""
    if not CAT_FILTER_CFG.exists():
        return set()
    data = json.loads(CAT_FILTER_CFG.read_text(encoding="utf-8"))
    return {k for k, v in data.get(key, {}).items() if v is False}


# Feed loading

def _read_csv(path: Path) -> list:
    # ANCHOR: when a feed has more CSV fields than header columns (embedded commas in
    # unquoted text fields like product_name/description), anchor the last ANCHOR header
    # columns to the last ANCHOR data fields so that price/stock are always correct.
    _ANCHOR = 4  # merchant_deep_link, merchant_image_url, search_price, in_stock
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = csv.reader(f)
        header = [k.strip() if k else "" for k in next(raw)]
        n = len(header)
        rows = []
        for raw_row in raw:
            m = len(raw_row)
            if m <= n:
                row = dict(zip(header, raw_row))
            else:
                # Anchor last _ANCHOR headers to last _ANCHOR data fields
                row = {}
                for i, h in enumerate(header[:-_ANCHOR]):
                    row[h] = raw_row[i]
                for i, h in enumerate(header[-_ANCHOR:]):
                    row[h] = raw_row[m - _ANCHOR + i]
            rows.append(row)
    return rows


def _load_feed(merchant: dict, local_feeds: dict) -> list:
    key  = merchant["key"]
    prog = merchant.get("awin_programme_id", "")

    if key in local_feeds:
        p = local_feeds[key]
        if not p.exists():
            print(f"  [{key}] Fichier local introuvable : {p}")
            return []
        rows = _read_csv(p)
        print(f"  [{key}] Flux local : {p.name} ({len(rows):,} produits)")
        CACHE_DIR.mkdir(exist_ok=True)
        cache_path = CACHE_DIR / f"feed_{prog}.csv"
        if not cache_path.exists():
            cache_path.write_bytes(p.read_bytes())
            print(f"       -> Cache : {cache_path.name}")
        return rows

    for cpath in [CACHE_DIR / f"rdc_feed_{prog}.csv", CACHE_DIR / f"feed_{prog}.csv"]:
        if cpath.exists():
            age_h = (time.time() - cpath.stat().st_mtime) / 3600
            rows  = _read_csv(cpath)
            print(f"  [{key}] Cache ({age_h:.0f}h) : {cpath.name} ({len(rows):,} produits)")
            return rows

    print(f"  [{key}] Aucun flux disponible -- fournis --feed KEY=PATH")
    return []


# Data helpers

def _get_category(row: dict, default: str = "") -> str:
    raw = (row.get("merchant_category") or row.get("category_name") or "").strip().strip('"')
    return raw or default


def _parse_price(s) -> Optional[float]:
    if not s:
        return None
    try:
        return float(str(s).replace(",", ".").strip())
    except ValueError:
        return None


def _parse_date(s: str) -> Optional[str]:
    """Parse AWIN valid_from / last_updated → ISO date YYYY-MM-DD ou None.
    Formats rencontrés : 'YYYY-MM-DD', 'DD/MM/YYYY', 'YYYY-MM-DD HH:MM:SS'.
    """
    if not s or not (s := s.strip()):
        return None
    import re as _re
    # YYYY-MM-DD (éventuellement suivi d'un horodatage)
    m = _re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # DD/MM/YYYY
    m = _re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def _parse_int(s) -> int:
    try:
        return max(0, int(float(str(s).strip())))
    except (ValueError, TypeError):
        return 0


def _is_in_stock(s) -> bool:
    return str(s).strip().lower() in ("1", "yes", "true", "in stock")


def _popularity_score(row: dict) -> float:
    reviews = _parse_int(row.get("reviews") or "0")
    rating  = float(row.get("average_rating") or "0") or 0.0
    price   = _parse_price(row.get("search_price") or "0") or 0.0
    score = reviews * max(0.1, rating / 5.0)
    if price > 0:
        score += math.log1p(price) * 0.5
    return score


def _sort_rows(rows: list, sort_by: str) -> list:
    if sort_by == "recency":
        def _dt(r):
            try:
                return datetime.fromisoformat(r.get("last_updated", "").strip().replace(" ", "T"))
            except Exception:
                return datetime.min
        return sorted(rows, key=_dt, reverse=True)
    elif sort_by == "price":
        return sorted(rows, key=lambda r: _parse_price(r.get("search_price")) or 0, reverse=True)
    else:
        return sorted(rows, key=_popularity_score, reverse=True)


def _infer_category_slug(mc: str) -> str:
    m = mc.lower()
    if any(w in m for w in ["tv", "tele", "hifi", "home cinema", "enceinte", "barre de son", "ampli"]):
        return "tv-hifi"
    if any(w in m for w in ["jeux video", "gaming", "console", "manette", "xbox", "playstation", "switch"]):
        return "gaming"
    if any(w in m for w in ["informatique", "ordinateur", "laptop", "portable", "imprimante", "clavier", "souris"]):
        return "informatique"
    if any(w in m for w in ["smartphone", "telephone", "mobile", "android", "iphone"]):
        return "smartphone"
    if any(w in m for w in ["photo", "camera", "surveillance", "optics"]):
        return "photo-video"
    if any(w in m for w in ["electromenager", "cuisine", "refrig", "lave-", "four", "aspirateur", "robot"]):
        return "electromenager"
    if any(w in m for w in ["maison", "jardin", "bricolage", "luminaire"]):
        return "maison-jardin"
    if any(w in m for w in ["securite", "alarme"]):
        return "securite"
    if any(w in m for w in ["fleur", "cadeau", "plante", "bouquet"]):
        return "cadeaux"
    return "divers"


# Payload builder

_NOW = datetime.now(timezone.utc).isoformat()


def _build_payload(row: dict, merchant: dict) -> Optional[dict]:
    """Construit le dict a upsert dans `products`. Retourne None si ligne invalide."""
    ext_id = (row.get("aw_product_id") or "").strip().strip('"')
    name   = (row.get("product_name") or "").strip().strip('"')[:200]
    brand  = (row.get("brand_name") or "").strip().strip('"')[:100]

    if not ext_id or not name:
        return None

    brand         = brand or "-"
    image         = (row.get("aw_image_url") or row.get("aw_thumb_url") or "").strip() or None
    ean           = (row.get("ean") or "").strip() or None
    mpn           = (row.get("mpn") or "").strip() or None
    affiliate_url = (row.get("aw_deep_link") or row.get("merchant_deep_link") or "").strip() or None

    price    = _parse_price(row.get("search_price"))
    currency = (row.get("currency") or "EUR").strip()[:3]
    in_stock = _is_in_stock(row.get("in_stock", "1"))

    rating: Optional[float] = None
    try:
        rv = float(str(row.get("average_rating") or "").strip())
        rating = round(min(5.0, max(0.0, rv)), 2) if rv else None
    except ValueError:
        pass

    review_count  = _parse_int(row.get("reviews") or "0")
    default_cat   = merchant.get("default_category", "")
    cat_raw       = _get_category(row, default_cat)
    category_slug = _infer_category_slug(cat_raw)

    # Description : nettoyage des guillemets résiduels (CSV non-proprement quoté)
    desc_raw = (row.get("description") or "").strip().strip('"').strip()
    # Fallback sur product_short_description ou specifications si description courte/vide
    if len(desc_raw) <= 5:
        desc_raw = (row.get("product_short_description") or "").strip().strip('"').strip()
    if len(desc_raw) <= 5:
        # specifications : ex "Résolution: 4K | Connectivité: WiFi | ..."
        specs = (row.get("specifications") or "").strip().strip('"').strip()
        if len(specs) > 5:
            desc_raw = specs[:2000]
    description = desc_raw[:2000] if len(desc_raw) > 5 else None

    # Date de sortie / disponibilité (valid_from ou last_updated du flux AWIN)
    release_date = (
        _parse_date(row.get("valid_from"))
        or _parse_date(row.get("last_updated"))
    )

    return {
        "external_id":       ext_id,
        "merchant_key":      merchant["key"],
        "merchant_name":     merchant.get("label", merchant["key"]),
        "name":              name,
        "brand":             brand,
        "image_url":         image,
        "ean":               ean,
        "mpn":               mpn,
        "rating":            rating,
        "review_count":      review_count,
        "price":             price,
        "currency":          currency,
        "in_stock":          in_stock,
        "affiliate_url":     affiliate_url,
        "merchant_category": cat_raw or None,
        "category_slug":     category_slug,
        "description":       description,
        "release_date":      release_date,
        "active":            True,
        "last_price_update": _NOW,
        "pros_fr":           json.dumps([]),
        "cons_fr":           json.dumps([]),
    }


# Batch Supabase operations

def _batch_upsert(payloads: list, dry_run: bool) -> int:
    """Upsert en batches de BATCH_SIZE. Retourne le nb de lignes traitees."""
    if dry_run or not payloads:
        return len(payloads)
    sb = _sb()
    for i in range(0, len(payloads), BATCH_SIZE):
        sb.table("products").upsert(
            payloads[i:i + BATCH_SIZE],
            on_conflict="external_id,merchant_key",
        ).execute()
    return len(payloads)


def _batch_deactivate(product_ids: list, dry_run: bool) -> int:
    """Soft-delete : active = false pour les produits absents du flux."""
    if dry_run or not product_ids:
        return len(product_ids)
    sb = _sb()
    for i in range(0, len(product_ids), BATCH_SIZE):
        sb.table("products").update({"active": False}).in_("id", product_ids[i:i + BATCH_SIZE]).execute()
    return len(product_ids)


def _fetch_existing(merchant_key: str) -> dict:
    """Retourne {external_id: {id, price, in_stock, ...}} pour ce marchand."""
    sb, page, size = _sb(), 0, 1000
    out: dict = {}
    while True:
        res = (
            sb.table("products")
            .select("id, external_id, price, in_stock, rating, review_count, image_url")
            .eq("merchant_key", merchant_key)
            .range(page * size, (page + 1) * size - 1)
            .execute()
        )
        for r in (res.data or []):
            if r.get("external_id"):
                out[r["external_id"]] = r
        if len(res.data or []) < size:
            break
        page += 1
    return out


# Filter pipeline

def _apply_filters(rows: list, merchant: dict, cfg: dict) -> list:
    key         = merchant["key"]
    excluded    = _excluded_categories(key)
    default_cat = merchant.get("default_category", "")
    min_p       = cfg.get("min_price")
    max_p       = cfg.get("max_price")

    out, injected = [], 0
    for row in rows:
        cat = _get_category(row)
        if not cat and default_cat:
            row = dict(row)
            row["merchant_category"] = default_cat
            cat = default_cat
            injected += 1

        if excluded and cat in excluded:
            continue

        price = _parse_price(row.get("search_price"))
        if min_p is not None and (price is None or price < min_p):
            continue
        if max_p is not None and price is not None and price > max_p:
            continue

        out.append(row)

    if injected:
        print(f"  [{key}] Categorie par defaut injectee : {injected:,}")
    excl = len(rows) - len(out)
    if excl:
        parts = []
        if excluded:
            parts.append(f"{len(excluded)} categories bloquees")
        if min_p is not None or max_p is not None:
            parts.append(f"prix [{min_p or 0}-{max_p or 'inf'}EUR]")
        print(f"  [{key}] Filtres : {excl:,} ({', '.join(parts)})")

    return out


# Commands

def cmd_first_import(merchants: list, local_feeds: dict, dry_run: bool):
    total = 0
    for merchant in merchants:
        key     = merchant["key"]
        cfg     = _db_cfg(key)
        limit   = cfg.get("first_import_limit", 500)
        sort_by = cfg.get("sort_by", "popularity")

        print(f"\n{'=' * 60}")
        print(f"  Premier import -- {merchant['label']} ({key})")
        print(f"  Limite: {limit:,}  |  Tri: {sort_by}")
        print(f"{'=' * 60}")

        rows = _load_feed(merchant, local_feeds)
        if not rows:
            continue

        rows     = _apply_filters(rows, merchant, cfg)
        rows     = _sort_rows(rows, sort_by)[:limit]
        payloads = [p for p in (_build_payload(r, merchant) for r in rows) if p]

        print(f"  -> {len(payloads):,} produits valides")

        if dry_run:
            print(f"\n  [DRY-RUN] Apercu des 5 premiers :")
            for p in payloads[:5]:
                print(f"    * {p['name'][:60]}")
                print(f"      {p['brand']:<20} {p.get('price') or 0:.2f} EUR  {p['merchant_category'] or '-'}")
            n_batches = math.ceil(len(payloads) / BATCH_SIZE) if payloads else 0
            print(f"\n  [DRY-RUN] {len(payloads):,} produits en {n_batches} batch(es) de {BATCH_SIZE}.")
            total += len(payloads)
            continue

        n_batches = math.ceil(len(payloads) / BATCH_SIZE) if payloads else 0
        _batch_upsert(payloads, dry_run=False)
        print(f"  OK  {len(payloads):,} produits importes en {n_batches} batch(es)")
        total += len(payloads)

    tag = " [DRY-RUN]" if dry_run else ""
    print(f"\n{'=' * 60}")
    print(f"  Total{tag} : {total:,} produits")
    print(f"{'=' * 60}")


def cmd_update(merchants: list, local_feeds: dict, dry_run: bool):
    for merchant in merchants:
        key           = merchant["key"]
        cfg           = _db_cfg(key)
        sort_by       = cfg.get("sort_by", "popularity")
        do_deactivate = cfg.get("delete_removed", True)
        max_new       = cfg.get("max_new_per_update", 1000)

        print(f"\n{'=' * 60}")
        print(f"  Mise a jour -- {merchant['label']} ({key})")
        print(f"{'=' * 60}")

        rows = _load_feed(merchant, local_feeds)
        if not rows:
            continue

        rows = _apply_filters(rows, merchant, cfg)

        feed_index: dict = {
            (r.get("aw_product_id") or "").strip().strip('"'): r
            for r in rows
            if (r.get("aw_product_id") or "").strip()
        }

        print(f"  Chargement des produits en base...")
        existing = _fetch_existing(key)

        feed_ids     = set(feed_index)
        existing_ids = set(existing)
        new_ids      = feed_ids - existing_ids
        removed_ids  = existing_ids - feed_ids
        common_ids   = feed_ids & existing_ids

        print(f"  Flux      : {len(feed_ids):>6,}")
        print(f"  En base   : {len(existing_ids):>6,}")
        print(f"  Nouveaux  : {len(new_ids):>6,}")
        print(f"  Absents   : {len(removed_ids):>6,}  -> soft-delete")
        print(f"  Communs   : {len(common_ids):>6,}  -> mise a jour")

        # 1. Nouveaux -> INSERT (tries, limites)
        new_rows     = _sort_rows([feed_index[i] for i in new_ids], sort_by)[:max_new]
        new_payloads = [p for p in (_build_payload(r, merchant) for r in new_rows) if p]
        n = _batch_upsert(new_payloads, dry_run)
        print(f"\n  +  {n:,} inseres" + (" [DRY-RUN]" if dry_run else ""))

        # 2. Absents -> active = false
        if do_deactivate and removed_ids:
            ids = [existing[ext]["id"] for ext in removed_ids if existing[ext].get("id")]
            n = _batch_deactivate(ids, dry_run)
            print(f"  -  {n:,} desactives" + (" [DRY-RUN]" if dry_run else ""))

        # 3. Communs -> UPSERT (met a jour price, in_stock, image, rating...)
        common_payloads = [
            p for p in (_build_payload(feed_index[ext], merchant) for ext in common_ids) if p
        ]
        n_batches = math.ceil(len(common_payloads) / BATCH_SIZE) if common_payloads else 0
        n = _batch_upsert(common_payloads, dry_run)
        print(f"  ~  {n:,} mis a jour en {n_batches} batch(es)" + (" [DRY-RUN]" if dry_run else ""))


def cmd_reset(yes: bool):
    """Vide TOUTES les tables Supabase (irreversible)."""
    if not yes:
        confirm = input("\nTape 'RESET' pour confirmer la suppression de toutes les donnees : ").strip()
        if confirm != "RESET":
            print("   Annule.")
            return

    sb = _sb()
    tables = ["top5_articles", "comparison_products", "affiliate_links",
              "pinterest_pins", "comparisons", "products", "categories"]
    print("\nVidage des tables...")
    for table in tables:
        try:
            sb.table(table).delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
            print(f"  OK  {table}")
        except Exception as e:
            print(f"  WARN  {table} : {e}")
    print("\nToutes les tables ont ete videes.")


# CLI

def main():
    p = argparse.ArgumentParser(
        description="Sync produits Awin <-> Supabase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--first-import", action="store_true",
                      help="Import initial (N produits les plus populaires par marchand)")
    mode.add_argument("--update",       action="store_true",
                      help="Mise a jour incrementale (insert/soft-delete/update)")
    mode.add_argument("--reset",        action="store_true",
                      help="Vider TOUTES les tables (irreversible)")

    p.add_argument("--merchant", metavar="KEY",
                   help="Limiter a un seul marchand (defaut: tous les marchands Awin actifs)")
    p.add_argument("--feed", action="append", metavar="KEY=PATH",
                   help="Flux local (ex: imou_fr=/path/feed.csv) -- repetable")
    p.add_argument("--dry-run", action="store_true",
                   help="Simuler sans ecrire en base")
    p.add_argument("--yes", "-y", action="store_true",
                   help="Confirmer --reset sans prompt")

    args = p.parse_args()

    local_feeds: dict = {}
    for entry in (args.feed or []):
        if "=" not in entry:
            print(f"Format invalide --feed '{entry}' (attendu: KEY=PATH)")
            continue
        k, _, v = entry.partition("=")
        local_feeds[k.strip()] = Path(v.strip())

    if args.reset:
        cmd_reset(args.yes)
        return

    all_merchants = _load_merchants()
    active_awin   = [m for m in all_merchants if m.get("network") == "awin" and m.get("active")]

    if args.merchant:
        merchants = [m for m in all_merchants if m["key"] == args.merchant]
        if not merchants:
            print(f"Marchand '{args.merchant}' introuvable dans merchants.json")
            sys.exit(1)
    else:
        merchants = active_awin

    if not merchants:
        print("Aucun marchand Awin actif -- verifier config/merchants.json")
        sys.exit(1)

    print(f"\nMarchands  : {', '.join(m['key'] for m in merchants)}")
    print(f"Batch size : {BATCH_SIZE} produits/appel")
    if args.dry_run:
        print("Mode       : DRY-RUN (aucune ecriture en base)")

    if args.first_import:
        cmd_first_import(merchants, local_feeds, args.dry_run)
    elif args.update:
        cmd_update(merchants, local_feeds, args.dry_run)


if __name__ == "__main__":
    main()
