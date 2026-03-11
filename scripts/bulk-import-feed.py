#!/usr/bin/env python3
"""
bulk-import-feed.py — Importe L'INTÉGRALITÉ du flux Awin (RdC) dans Supabase.
=============================================================================

Contrairement à import-awin-feed.py (qui crée des comparatifs 1 par 1 avec 5 produits),
ce script importe TOUS les produits du flux CSV en une passe.

Pré-requis
──────────
1. Avoir appliqué la migration 003_bulk_import_support.sql dans Supabase SQL Editor
2. Avoir le fichier CSV dans .cache/rdc_feed_6901.csv
   (ou utiliser --local-feed /chemin/vers/feed.csv)
3. Variables dans .env.local :
     NEXT_PUBLIC_SUPABASE_URL=...
     SUPABASE_SERVICE_ROLE_KEY=...

Usage
─────
  # Import complet (toutes catégories)
  python3 scripts/bulk-import-feed.py

  # Limiter à N produits pour tester
  python3 scripts/bulk-import-feed.py --limit 500

  # Fichier CSV custom
  python3 scripts/bulk-import-feed.py --local-feed /tmp/feed.csv

  # Forcer le re-téléchargement du flux depuis Awin
  python3 scripts/bulk-import-feed.py --force-download

  # Filtrer à certaines catégories CSV (ex: tech uniquement)
  python3 scripts/bulk-import-feed.py --only-tech

  # Recalculer les embeddings pour tous les produits importés
  python3 scripts/bulk-import-feed.py --embeddings

Performance estimée
───────────────────
  14 921 produits × batch 200 = ~75 batches
  Sans embeddings : ~3-5 min
  Avec embeddings  : ~8-12 min (sentence-transformers CPU)
"""

import argparse
import csv
import os
import sys
import time
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


# ── Config ────────────────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

AWIN_API_TOKEN      = os.getenv("AWIN_API_TOKEN", "")
AWIN_PRODUCTDATA_KEY = os.getenv("AWIN_PRODUCTDATA_KEY") or AWIN_API_TOKEN
AWIN_PUBLISHER_ID   = os.getenv("AWIN_PUBLISHER_ID", "")
AWIN_FEED_ID_RDC    = os.getenv("AWIN_FEED_ID_RDC", "")

RDC_PROGRAMME_ID = "6901"
RDC_PARTNER_KEY  = "rue-du-commerce"
RDC_COUNTRY      = "fr"

CACHE_DIR  = Path(__file__).parent.parent / ".cache"
BATCH_SIZE = 200  # produits par appel Supabase

# ── Mapping catégories CSV → slugs internes ───────────────────────────────────
# Toutes les merchant_category du flux RdC (top extraites par --list-categories)
CATEGORY_MAP: dict[str, str] = {
    # TV / Hi-Fi / Audio / Vidéo
    "TV":                               "tv-hifi",
    "Vidéoprojecteur":                  "tv-hifi",
    "Enceinte bluetooth":               "tv-hifi",
    "Enceinte wifi":                    "tv-hifi",
    "Barre de son":                     "tv-hifi",
    "Casque":                           "tv-hifi",
    "Casque audio":                     "tv-hifi",
    "Chaîne Hi-Fi":                     "tv-hifi",
    "Support TV":                       "tv-hifi",
    "Lecteur Blu-ray":                  "tv-hifi",
    "Ampli HiFi":                       "tv-hifi",
    # Gaming
    "Micro-casque":                     "gaming",
    "Fauteuil gamer":                   "gaming",
    "Manette":                          "gaming",
    "Volant gaming":                    "gaming",
    "Clavier gaming":                   "gaming",
    "Souris gaming":                    "gaming",
    "Tapis de souris":                  "gaming",
    # Informatique — Périphériques
    "Clavier":                          "informatique",
    "Souris":                           "informatique",
    "Écran PC":                         "informatique",
    "Ecran PC":                         "informatique",
    "Imprimante":                       "informatique",
    "Scanner":                          "informatique",
    "Webcam":                           "informatique",
    "Micro":                            "informatique",
    "Tablette graphique":               "informatique",
    # Informatique — Composants
    "PC portable":                      "informatique",
    "PC":                               "informatique",
    "RAM PC":                           "informatique",
    "Boitier PC":                       "informatique",
    "Carte mère":                       "informatique",
    "Carte graphique":                  "informatique",
    "Processeur":                       "informatique",
    "SSD":                              "informatique",
    "Disque dur interne":               "informatique",
    "Disque dur SSD NAS":               "informatique",
    "Refroidissement":                  "informatique",
    "Watercooling":                     "informatique",
    "Alimentation PC":                  "informatique",
    # Informatique — Stockage & Réseau
    "Disque dur externe":               "informatique",
    "Clé USB":                          "informatique",
    "Hub USB":                          "informatique",
    "Station d'accueil PC portable":    "informatique",
    "Switch réseau":                    "informatique",
    "Modem, routeur & point d'accès":   "informatique",
    "Répéteur WiFi":                    "informatique",
    "Onduleur":                         "informatique",
    # Informatique — Câbles & Accessoires
    "Câble USB":                        "informatique",
    "Câble HDMI":                       "informatique",
    "Câble RJ45":                       "informatique",
    "Câble alimentation":               "informatique",
    "Câble DisplayPort":                "informatique",
    "Sacoche, housse & sac à dos PC portable": "informatique",
    "Housse & étui PC portable":        "informatique",
    # Smartphone & Tablette
    "Smartphone Android":               "smartphone",
    "Coque & étui smartphone":          "smartphone",
    "Apple Watch":                      "smartphone",
    "Tablette":                         "smartphone",
    "Smartwatch":                       "smartphone",
    "Accessoire smartphone":            "smartphone",
    # Electroménager
    "Robot cuiseur":                    "electromenager",
    "Aspirateur robot":                 "electromenager",
    "Aspirateur":                       "electromenager",
    "Aspirateur sans fil":              "electromenager",
    "Climatiseur":                      "electromenager",
    "Machine à café":                   "electromenager",
    "Four":                             "electromenager",
    "Lave-linge":                       "electromenager",
    "Sèche-linge":                      "electromenager",
    "Réfrigérateur":                    "electromenager",
    "Lave-vaisselle":                   "electromenager",
    "Mixeur":                           "electromenager",
    "Bouilloire":                       "electromenager",
    "Grille-pain":                      "electromenager",
}

# Catégories à IGNORER (faible valeur pour un comparateur tech)
SKIP_CATEGORIES: set[str] = {
    "Cartouche d'encre",
    "Toner",
    "Lego",
}

# Slugs de catégories à auto-créer si inexistantes
DEFAULT_CATEGORIES = {
    "tv-hifi":       ("TV & Hi-Fi",      "📺"),
    "gaming":        ("Gaming",          "🎮"),
    "informatique":  ("Informatique",    "💻"),
    "smartphone":    ("Smartphone",      "📱"),
    "electromenager":("Électroménager",  "🏠"),
    "divers":        ("Divers",          "🛒"),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_price(price_str: str) -> Optional[float]:
    try:
        return round(float(str(price_str).replace(",", ".").strip()), 2)
    except (ValueError, AttributeError):
        return None


def _is_in_stock(row: dict) -> bool:
    val = (row.get("in_stock") or row.get("stock_status") or "").lower().strip()
    return val in ("1", "yes", "true", "en stock", "in stock")


def _tracking_url(row: dict) -> str:
    aw = (row.get("aw_deep_link") or "").strip()
    if aw:
        return aw
    raw = (row.get("merchant_deep_link") or "").strip()
    if raw and AWIN_PUBLISHER_ID:
        return (
            f"https://www.awin1.com/cread.php"
            f"?awinmid={RDC_PROGRAMME_ID}&awinaffid={AWIN_PUBLISHER_ID}"
            f"&ued={quote(raw, safe='')}"
        )
    return raw


def _map_category(merchant_category: str) -> str:
    return CATEGORY_MAP.get(merchant_category, "divers")


_sb_client: Optional[Client] = None


def _sb() -> Client:
    global _sb_client
    if _sb_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            print("❌  NEXT_PUBLIC_SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis dans .env.local")
            sys.exit(1)
        _sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sb_client


# ── Feed loading ──────────────────────────────────────────────────────────────

def load_feed(local_path: Optional[str] = None, force_download: bool = False) -> list[dict]:
    if local_path:
        path = Path(local_path)
        if not path.exists():
            print(f"❌  Fichier introuvable : {local_path}")
            sys.exit(1)
        print(f"📂  Flux local : {path} ({path.stat().st_size // 1024:,} Ko)")
    else:
        path = CACHE_DIR / f"rdc_feed_{RDC_PROGRAMME_ID}.csv"
        if path.exists() and not force_download:
            age_h = (time.time() - path.stat().st_mtime) / 3600
            print(f"📂  Cache : {path.name} ({path.stat().st_size // 1024:,} Ko, {age_h:.0f}h)")
        else:
            # Tente téléchargement via l'API Awin
            if not AWIN_PRODUCTDATA_KEY:
                print("⚠️  AWIN_PRODUCTDATA_KEY absent — utilise le cache existant si disponible")
                if not path.exists():
                    print("❌  Aucun fichier .cache/rdc_feed_*.csv trouvé.")
                    print("   Télécharge manuellement le CSV depuis Awin UI et utilise --local-feed")
                    sys.exit(1)
            else:
                _download_feed(path)

    with open(path, encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
    print(f"  → {len(rows):,} lignes dans le flux\n")
    return rows


def _download_feed(dest: Path):
    """Télécharge le flux RdC depuis Awin ProductData API."""
    FEED_COLUMNS = ",".join([
        "aw_product_id", "product_name", "brand_name",
        "aw_image_url", "aw_thumb_url",
        "ean", "search_price", "currency",
        "merchant_deep_link", "aw_deep_link",
        "in_stock", "last_updated",
        "category_name", "description",
        "merchant_category", "average_rating", "reviews",
    ])
    feed_id = AWIN_FEED_ID_RDC
    if not feed_id:
        print("⚠️  AWIN_FEED_ID_RDC non défini — tentative de découverte auto…")
        feed_id = _discover_feed_id()
        if not feed_id:
            print("❌  Impossible de découvrir le Feed ID. Définir AWIN_FEED_ID_RDC dans .env.local")
            sys.exit(1)

    import gzip, io
    url = (
        f"https://productdata.awin.com/datafeed/download/apikey/{AWIN_PRODUCTDATA_KEY}"
        f"/language/fr/fid/{feed_id}/columns/{FEED_COLUMNS}/format/csv/compression/gzip/"
    )
    print(f"⬇️  Téléchargement du flux (feed_id={feed_id})…")
    CACHE_DIR.mkdir(exist_ok=True)
    resp = requests.get(url, timeout=120, stream=True)
    if resp.status_code != 200:
        print(f"❌  HTTP {resp.status_code} : {resp.text[:200]}")
        sys.exit(1)
    raw = gzip.decompress(resp.content)
    dest.write_bytes(raw if not raw.startswith(b'\xef\xbb\xbf') else raw[3:])
    print(f"  ✓ Téléchargé : {dest.stat().st_size // 1024:,} Ko")


def _discover_feed_id() -> Optional[str]:
    url = f"https://legacydatafeeds.awin.com/datafeed/list/apikey/{AWIN_PRODUCTDATA_KEY}/format/csv/"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            return None
        import io
        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            if row.get("Advertiser ID", "").strip().strip('"') == RDC_PROGRAMME_ID:
                fid = row.get("Feed ID", "").strip().strip('"')
                if fid:
                    return fid
    except Exception:
        pass
    return None


# ── Embedding (optionnel) ─────────────────────────────────────────────────────

_embedding_model = None


def _load_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            print("   📦 Chargement modèle embedding (1re fois ~10s)…")
            _embedding_model = SentenceTransformer("intfloat/multilingual-e5-small")
            print("   ✓ Modèle prêt")
        except ImportError:
            print("   ⚠️  sentence-transformers non installé — embeddings ignorés")
            print("      pip install sentence-transformers  puis relance avec --embeddings")
            _embedding_model = "UNAVAILABLE"
    return _embedding_model if _embedding_model != "UNAVAILABLE" else None


def _batch_embed(texts: list[str]) -> list[Optional[list]]:
    model = _load_embedding_model()
    if model is None:
        return [None] * len(texts)
    prefixed = [f"passage: {t}" for t in texts]
    vecs = model.encode(prefixed, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    return [v.tolist() for v in vecs]


# ── Categories bootstrap ──────────────────────────────────────────────────────

def _ensure_categories(slugs_needed: set[str]):
    sb = _sb()
    existing = {r["slug"] for r in sb.table("categories").select("slug").execute().data}
    for slug in slugs_needed:
        if slug not in existing:
            name_fr, icon = DEFAULT_CATEGORIES.get(slug, (slug.replace("-", " ").title(), "🛒"))
            sb.table("categories").insert({
                "slug": slug, "name_fr": name_fr,
                "name_en": name_fr, "name_de": name_fr,
                "icon": icon, "is_active": True, "display_order": 0,
            }).execute()
            print(f"  + Catégorie créée : {slug}")


# ── Bulk import ───────────────────────────────────────────────────────────────

def bulk_import(rows: list[dict], limit: int = 0, generate_embeddings: bool = False,
                only_tech: bool = False, dry_run: bool = False):
    sb = _sb()

    # ── Filtrer les lignes ────────────────────────────────────────────────────
    filtered = []
    skipped_cat = 0
    skipped_price = 0
    for row in rows:
        cat = row.get("merchant_category", "") or ""
        if cat in SKIP_CATEGORIES:
            skipped_cat += 1
            continue
        if only_tech and _map_category(cat) not in {"tv-hifi", "gaming", "informatique", "smartphone"}:
            skipped_cat += 1
            continue
        price = _parse_price(row.get("search_price", ""))
        if not price:
            skipped_price += 1
            continue
        filtered.append(row)

    if limit > 0:
        filtered = filtered[:limit]

    total = len(filtered)
    print(f"📊  {total:,} produits à importer ({skipped_cat:,} catégories exclues, {skipped_price:,} sans prix)\n")

    if dry_run:
        print("[DRY-RUN] Rien n'est écrit en base.")
        cats = {_map_category(r.get("merchant_category", "")) for r in filtered}
        print(f"  Catégories concernées : {sorted(cats)}")
        return

    # ── Bootstrap catégories ──────────────────────────────────────────────────
    used_cats = {_map_category(r.get("merchant_category", "")) for r in filtered}
    _ensure_categories(used_cats)

    # ── Pré-chargement de TOUS les external_id existants en mémoire ───────────
    # (évite tout ON CONFLICT SQL — fonctionne sans index unique)
    print("🔗  Chargement des produits existants…")
    existing_ext_map: dict[str, str] = {}   # external_id → product_id
    existing_by_name: dict[str, str] = {}   # name → product_id (fallback reconciliation)
    page = 0
    while True:
        res = sb.table("products").select("id, name, external_id").range(
            page * 1000, (page + 1) * 1000 - 1
        ).execute()
        if not res.data:
            break
        for p in res.data:
            existing_by_name[p["name"]] = p["id"]
            if p.get("external_id"):
                existing_ext_map[p["external_id"]] = p["id"]
        if len(res.data) < 1000:
            break
        page += 1

    print(f"  → {len(existing_by_name):,} produits existants ({len(existing_ext_map):,} avec external_id)\n")

    # ── Import par batches ────────────────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    products_new = 0
    products_skip = 0
    links_done = 0
    errors = 0

    batches = [filtered[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    nb_batches = len(batches)

    if generate_embeddings:
        _load_embedding_model()

    for batch_idx, batch in enumerate(batches, 1):
        t0 = time.time()

        # ── Séparer nouveaux produits vs existants ────────────────────────────
        new_rows: list[dict] = []
        existing_rows: list[dict] = []
        for row in batch:
            ext_id = (row.get("aw_product_id") or "").strip()
            name   = (row.get("product_name") or "").strip()[:200]
            if ext_id and ext_id in existing_ext_map:
                existing_rows.append(row)
            elif name and name in existing_by_name and not ext_id:
                existing_rows.append(row)
            else:
                new_rows.append(row)

        # ── Préparer rich_texts & embeddings pour les nouveaux ────────────────
        rich_texts_new = []
        for row in new_rows:
            name     = (row.get("product_name") or "").strip()[:200]
            brand    = (row.get("brand_name")   or "—").strip()[:100]
            cat_slug = _map_category(row.get("merchant_category", ""))
            parts    = [name]
            if brand and brand != "—":
                parts.append(f"Marque: {brand}")
            parts.append(f"Catégorie: {cat_slug.replace('-', ' ')}")
            rich_texts_new.append(" — ".join(parts))

        embeddings_new: list[Optional[list]] = [None] * len(new_rows)
        if generate_embeddings and new_rows:
            embeddings_new = _batch_embed(rich_texts_new)

        # ── Construire payloads pour les nouveaux ─────────────────────────────
        new_payloads = []
        for i, row in enumerate(new_rows):
            name     = (row.get("product_name") or "").strip()[:200]
            brand    = (row.get("brand_name")   or "—").strip()[:100]
            image    = (row.get("aw_image_url") or row.get("aw_thumb_url") or "").strip()
            rating   = _parse_price(row.get("average_rating", ""))
            reviews  = int(row.get("reviews") or 0)
            ext_id   = (row.get("aw_product_id") or "").strip()
            ean      = (row.get("ean") or "").strip() or None
            cat_slug = _map_category(row.get("merchant_category", ""))
            rich_text = f"passage: {rich_texts_new[i]}"

            payload: dict = {
                "name": name,
                "brand": brand,
                "image_url": image or None,
                "review_count": reviews,
                "category_slug": cat_slug,
                "rich_text": rich_text,
                "external_id": ext_id or None,
                "ean": ean,
                "pros_fr": "[]",
                "cons_fr": "[]",
            }
            if rating is not None and 0 <= rating <= 5:
                payload["rating"] = rating
            if embeddings_new[i] is not None:
                payload["embedding"] = embeddings_new[i]
            new_payloads.append(payload)

        # ── INSERT nouveaux produits (pas de conflit possible) ────────────────
        inserted: list[dict] = []
        if new_payloads:
            try:
                res = sb.table("products").insert(new_payloads).execute()
                inserted = res.data or []
                products_new += len(inserted)
                # Mettre à jour le cache local
                for p in inserted:
                    if p.get("external_id"):
                        existing_ext_map[p["external_id"]] = p["id"]
                    existing_by_name[p["name"]] = p["id"]
            except Exception as e:
                print(f"\n  ❌  Batch {batch_idx}/{nb_batches} — erreur insert : {e}")
                errors += 1

        products_skip += len(existing_rows)

        # ── Construire la map ext_id → product_id pour TOUT le batch ─────────
        ext_to_id: dict[str, str] = {}
        for row in batch:
            ext_id = (row.get("aw_product_id") or "").strip()
            name   = (row.get("product_name") or "").strip()[:200]
            pid = None
            if ext_id:
                pid = existing_ext_map.get(ext_id)
            if pid is None:
                pid = existing_by_name.get(name)
            if pid:
                ext_to_id[ext_id or name] = pid

        # ── affiliate_links : supprimer puis réinsérer (pas besoin d'index) ───
        prod_ids_batch = list({v for v in ext_to_id.values()})
        if prod_ids_batch:
            try:
                # Supprimer les liens bulk existants (comparison_id IS NULL)
                sb.table("affiliate_links").delete().in_(
                    "product_id", prod_ids_batch
                ).is_("comparison_id", "null").execute()
            except Exception:
                pass  # table vide = pas d'erreur critique

        link_payloads = []
        for row in batch:
            ext_id  = (row.get("aw_product_id") or "").strip()
            name    = (row.get("product_name") or "").strip()[:200]
            key     = ext_id or name
            prod_id = ext_to_id.get(key)
            if not prod_id:
                continue
            price = _parse_price(row.get("search_price", ""))
            url   = _tracking_url(row)
            if not url:
                continue
            link_payloads.append({
                "product_id":      prod_id,
                "comparison_id":   None,
                "partner":         RDC_PARTNER_KEY,
                "country":         RDC_COUNTRY,
                "url":             url,
                "price":           price,
                "currency":        "EUR",
                "in_stock":        _is_in_stock(row),
                "commission_rate": 3.0,
                "last_checked":    now,
            })

        if link_payloads:
            try:
                sb.table("affiliate_links").insert(link_payloads).execute()
                links_done += len(link_payloads)
            except Exception as e:
                print(f"\n  ⚠️  Batch {batch_idx}/{nb_batches} — erreur liens : {e}")

        elapsed = time.time() - t0
        pct = batch_idx / nb_batches * 100
        eta = (nb_batches - batch_idx) * elapsed
        print(
            f"  Batch {batch_idx:3d}/{nb_batches}  "
            f"+{products_new:5,d} nouveaux  "
            f"~{products_skip:5,d} existants  "
            f"{links_done:6,d} liens  "
            f"[{pct:4.1f}%]  eta ~{eta/60:.1f}min",
            end="\r" if batch_idx < nb_batches else "\n",
        )

    print(f"\n{'─'*60}")
    print(f"✅  Import terminé !")
    print(f"   Nouveaux produits : {products_new:,}")
    print(f"   Déjà existants    : {products_skip:,}")
    print(f"   Liens affiliés    : {links_done:,}")
    if errors:
        print(f"   Erreurs           : {errors}")
    print(f"{'─'*60}")

    if not generate_embeddings:
        print("\n💡  Embeddings non générés (mode rapide).")
        print("   Pour les générer :")
        print("   python3 scripts/generate-embeddings.py --force")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Import bulk du flux Awin RdC → Supabase")
    parser.add_argument("--local-feed",      metavar="PATH", help="CSV local au lieu du cache")
    parser.add_argument("--force-download",  action="store_true", help="Retélécharge le flux")
    parser.add_argument("--limit",           type=int, default=0,   help="Limiter à N produits (test)")
    parser.add_argument("--only-tech",       action="store_true",   help="Tech uniquement (TV/gaming/info/phone)")
    parser.add_argument("--embeddings",      action="store_true",   help="Générer les embeddings (plus lent)")
    parser.add_argument("--dry-run",         action="store_true",   help="Affiche stats sans écrire en base")
    args = parser.parse_args()

    print("═" * 60)
    print("  Bulk Import — Flux Rue du Commerce → Supabase")
    print("═" * 60)
    print()

    rows = load_feed(args.local_feed, args.force_download)
    bulk_import(
        rows,
        limit=args.limit,
        generate_embeddings=args.embeddings,
        only_tech=args.only_tech,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
