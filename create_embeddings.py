#!/usr/bin/env python3
"""
create_embeddings.py — Génère les embeddings vectoriels pour les produits
=========================================================================

Modèle  : BAAI/bge-m3  (1024 dims, multilingue)
DB      : Supabase — colonnes products.embedding + products.embedding_text

Usage :
    python3 scripts/create_embeddings.py                 # Non-embedés uniquement
    python3 scripts/create_embeddings.py --force         # Re-générer tout
    python3 scripts/create_embeddings.py --limit 5 --dry-run
"""

import argparse
import re
import sys
import time

import requests

from settings import SUPABASE_URL, SUPABASE_KEY, sb_headers, check_supabase

# ── Config ────────────────────────────────────────────────────────────────────
MODEL_NAME = "BAAI/bge-m3"
BATCH_SIZE = 8
PAGE_SIZE = 1000

# ── Nettoyage du titre ────────────────────────────────────────────────────────
_RE_PRICE = re.compile(r'\d+[,\.]?\d*\s*[€$£]|[€$£]\s*\d+[,\.]?\d*')
_RE_PROMO = re.compile(r'-\d+\s*%|\+\d+\s*%', re.IGNORECASE)
_RE_NOISE = re.compile(
    r'\b(en stock|rupture|livraison gratuite|offre|promo|soldes|neuf|reconditionn[ée]|\bhs\b)\b',
    re.IGNORECASE,
)


def _clean_title(title: str) -> str:
    title = _RE_PRICE.sub('', title)
    title = _RE_PROMO.sub('', title)
    title = _RE_NOISE.sub('', title)
    return re.sub(r'\s{2,}', ' ', title).strip()


def build_rich_text(product: dict) -> str:
    """brand + title (nettoyé) + catégorie + mpn — pas de préfixe pour BGE-M3."""
    brand = product.get("brand") or ""
    name = _clean_title(product.get("name") or "")
    merchant_cat = product.get("merchant_category") or ""
    cat_slug = (product.get("category_slug") or "").replace("-", " ")
    cat_label = merchant_cat or cat_slug
    mpn = product.get("mpn") or ""
    return " ".join(p for p in [brand, name, cat_label, mpn] if p)


# ── Supabase helpers ─────────────────────────────────────────────────────────

def sb_get(path: str, params: str = "") -> list:
    url = f"{SUPABASE_URL}/rest/v1/{path}{'?' + params if params else ''}"
    r = requests.get(url, headers=sb_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def sb_patch(pid: str, data: dict) -> None:
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/products?id=eq.{pid}",
        headers=sb_headers({"Prefer": "return=minimal"}),
        json=data, timeout=30,
    )
    if r.status_code not in (200, 204):
        raise RuntimeError(f"PATCH {pid} → {r.status_code}: {r.text[:200]}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Génère les embeddings produits")
    parser.add_argument("--force", action="store_true", help="Re-générer tous les produits")
    parser.add_argument("--limit", type=int, default=0, help="Limiter à N produits (0 = tous)")
    parser.add_argument("--dry-run", action="store_true", help="Ne rien écrire en base")
    args = parser.parse_args()

    check_supabase()

    # Lazy import : sentence-transformers est lourd
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("❌ pip install sentence-transformers")
        sys.exit(1)

    print(f"📦  Chargement du modèle {MODEL_NAME}…")
    t0 = time.time()
    model = SentenceTransformer(MODEL_NAME)
    print(f"   ✓ Modèle chargé en {time.time() - t0:.1f}s")

    # Récupérer les produits
    fields = "select=id,name,brand,category_slug,merchant_category,mpn"
    extra_filter = "" if args.force else "&embedding=is.null"
    products: list[dict] = []
    offset = 0
    while True:
        page = sb_get("products", f"{fields}{extra_filter}&order=created_at.desc&limit={PAGE_SIZE}&offset={offset}")
        products.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        if args.limit and len(products) >= args.limit:
            products = products[:args.limit]
            break

    total = len(products)
    print(f"   → {total} produit(s) à traiter")
    if total == 0:
        print("✅  Rien à faire.")
        return

    # Construction des textes
    rich_texts = [build_rich_text(p) for p in products]
    if rich_texts:
        print(f"   ex: {rich_texts[0][:120]}")

    # Génération embeddings
    print(f"🧠  Génération embeddings ({BATCH_SIZE}/batch)…")
    t_emb = time.time()
    embeddings = model.encode(
        rich_texts, batch_size=BATCH_SIZE,
        show_progress_bar=True, normalize_embeddings=True,
    )
    print(f"   ✓ {total} embeddings en {time.time() - t_emb:.1f}s")

    # Upsert Supabase
    ok = errors = 0
    for i, (product, embedding, text) in enumerate(zip(products, embeddings, rich_texts)):
        if args.dry_run:
            print(f"  [DRY] {product['name'][:60]} → dim={len(embedding)}")
            ok += 1
            continue
        try:
            sb_patch(product["id"], {"embedding": embedding.tolist(), "embedding_text": text})
            ok += 1
            if (i + 1) % 10 == 0 or i == total - 1:
                print(f"  [{i + 1}/{total}] ✓")
        except Exception as e:
            errors += 1
            print(f"  [{i + 1}/{total}] ❌ {product['name'][:40]}: {e}")

    print(f"\n{'🎉' if errors == 0 else '⚠️'}  Terminé : {ok} OK, {errors} erreurs")


if __name__ == "__main__":
    main()
