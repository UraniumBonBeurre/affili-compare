#!/usr/bin/env python3
"""
generate-embeddings.py — Génère les embeddings vectoriels pour tous les produits
=================================================================================

Modèle  : BAAI/bge-m3  (1024 dims, multilingue, ~570 Mo, state-of-the-art 2024-2026)
Prefix  : aucun — BGE-M3 encode les documents sans préfixe
DB      : Supabase — colonne products.embedding (schéma v2)

Installation :
    pip install sentence-transformers requests python-dotenv

Usage :
    # Tous les produits sans embedding
    python3 scripts/generate-embeddings.py

    # Forcer la re-génération de tous les produits
    python3 scripts/generate-embeddings.py --force

    # Tester sur les 5 premiers
    python3 scripts/generate-embeddings.py --limit 5 --dry-run

Variables d'env requises (dans .env.local) :
    NEXT_PUBLIC_SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# ── Chargement .env.local ──────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
env_path = ROOT / ".env.local"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY manquants dans .env.local")
    sys.exit(1)

# ── Import lazy (après vérif des envs) ────────────────────────────────────────
try:
    import requests
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("❌ Dépendances manquantes. Exécute : pip install sentence-transformers requests")
    sys.exit(1)

# ── Configuration ─────────────────────────────────────────────────────────────
MODEL_NAME   = "BAAI/bge-m3"   # 1024 dims, ~570 Mo, state-of-the-art multilingue
BATCH_SIZE   = 8               # bge-m3 est plus lourd, batch plus petit
HEADERS      = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}


# ── Helpers Supabase ──────────────────────────────────────────────────────────
def sb_get(path: str, params: str = "") -> list:
    url = f"{SUPABASE_URL}/rest/v1/{path}{'?' + params if params else ''}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def sb_patch(path: str, data: dict) -> None:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    r = requests.patch(url, headers=HEADERS, json=data, timeout=30)
    if r.status_code not in (200, 204):
        raise RuntimeError(f"PATCH {path} → {r.status_code}: {r.text[:200]}")


# ── Nettoyage du titre ────────────────────────────────────────────────────────
_RE_PRICE   = re.compile(r'\d+[,\.]?\d*\s*[€$£]|[€$£]\s*\d+[,\.]?\d*')
_RE_PROMO   = re.compile(r'-\d+\s*%|\+\d+\s*%', re.IGNORECASE)
_RE_NOISE   = re.compile(
    r'\b(en stock|rupture|livraison gratuite|offre|promo|soldes|neuf|reconditionn[ée]|\bhs\b)\b',
    re.IGNORECASE,
)

def _clean_title(title: str) -> str:
    """Retire prix, pourcentages et mots parasites du titre."""
    title = _RE_PRICE.sub('', title)
    title = _RE_PROMO.sub('', title)
    title = _RE_NOISE.sub('', title)
    return re.sub(r'\s{2,}', ' ', title).strip()


# ── Construction du texte à embedder ────────────────────────────────────────
def build_rich_text(product: dict) -> str:
    """
    Ordre de priorité (recommandé e-commerce 2026) :
      brand → title (nettoyé) → catégorie → mpn
    BGE-M3 : pas de préfixe pour les documents.
    """
    brand        = product.get("brand") or ""
    name         = _clean_title(product.get("name") or "")
    merchant_cat = product.get("merchant_category") or ""
    cat_slug     = (product.get("category_slug") or "").replace("-", " ")
    cat_label    = merchant_cat or cat_slug
    mpn          = product.get("mpn") or ""

    parts = [brand, name, cat_label, mpn]
    text  = " ".join(p for p in parts if p)
    return text


# ── Helpers pagination ────────────────────────────────────────────────────────
def sb_get_all(path: str, base_params: str = "") -> list:
    """Récupère toutes les pages d'une table (pagination 1000/page)."""
    results = []
    page_size = 1000
    offset = 0
    while True:
        sep = "&" if base_params else ""
        params = f"{base_params}{sep}limit={page_size}&offset={offset}"
        page = sb_get(path, params)
        results.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return results


# ── Résolution catégorie (join products → comparison_products → comparisons → categories) ──
ID_BATCH = 80  # Keep URLs well under ~8 KB


def _batched(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def resolve_category_slugs(product_ids: list[str]) -> dict[str, str]:
    """Retourne {product_id: category_slug} pour tous les ids donnés (batch-safe)."""
    if not product_ids:
        return {}

    # 1. comparison_products — batch par ID_BATCH pour rester sous la limite d'URL
    cp_rows: list[dict] = []
    for batch in _batched(product_ids, ID_BATCH):
        ids_param = ",".join(batch)
        rows = sb_get("comparison_products", f"product_id=in.({ids_param})&select=product_id,comparison_id")
        cp_rows.extend(rows)

    if not cp_rows:
        return {}

    comp_ids = list({r["comparison_id"] for r in cp_rows})

    # 2. comparisons → category_id
    comps: list[dict] = []
    for batch in _batched(comp_ids, ID_BATCH):
        comp_ids_param = ",".join(batch)
        rows = sb_get("comparisons", f"id=in.({comp_ids_param})&select=id,category_id&is_published=eq.true")
        comps.extend(rows)
    comp_to_cat = {c["id"]: c["category_id"] for c in comps if c.get("category_id")}

    # 3. categories → slug
    cat_ids = list(set(comp_to_cat.values()))
    if not cat_ids:
        return {}
    cats: list[dict] = []
    for batch in _batched(cat_ids, ID_BATCH):
        cat_ids_param = ",".join(batch)
        rows = sb_get("categories", f"id=in.({cat_ids_param})&select=id,slug")
        cats.extend(rows)
    cat_to_slug = {c["id"]: c["slug"] for c in cats}

    # 4. Assemblage product_id → slug
    comp_to_slug = {cid: cat_to_slug.get(catid, "") for cid, catid in comp_to_cat.items()}
    result: dict[str, str] = {}
    for row in cp_rows:
        pid   = row["product_id"]
        cmpid = row["comparison_id"]
        slug  = comp_to_slug.get(cmpid, "")
        if slug and pid not in result:
            result[pid] = slug

    return result


# ── Programme principal ────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Génère les embeddings produits")
    parser.add_argument("--force",   action="store_true", help="Re-générer tous les produits (même ceux déjà embedés)")
    parser.add_argument("--limit",   type=int, default=0, help="Limiter à N produits (0 = tous)")
    parser.add_argument("--dry-run", action="store_true", help="Ne rien écrire en base")
    args = parser.parse_args()

    # 1. Charger le modèle
    print(f"📦 Chargement du modèle {MODEL_NAME} …")
    t0 = time.time()
    model = SentenceTransformer(MODEL_NAME)
    print(f"   ✓ Modèle chargé en {time.time()-t0:.1f}s")

    # 2. Récupérer les produits (pagination pour dépasser la limite de 1000 de PostgREST)
    PAGE = 1000
    fields = "select=id,name,brand,category_slug,merchant_category,mpn"
    if args.force:
        print("🔁 Mode --force : re-génération de tous les produits (paginé) …")
        extra_filter = ""
    else:
        print("⏳ Produits sans embedding (paginé) …")
        extra_filter = "&embedding=is.null"

    products: list = []
    offset = 0
    while True:
        page = sb_get("products", f"{fields}{extra_filter}&order=created_at.desc&limit={PAGE}&offset={offset}")
        products.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
        if args.limit and len(products) >= args.limit:
            products = products[:args.limit]
            break

    total = len(products)
    print(f"   → {total} produit(s) à traiter")
    if total == 0:
        print("✅ Rien à faire.")
        return

    # 3. Construire les rich_texts (category_slug + merchant_category déjà dans le produit)
    print("📝 Construction des textes …")
    rich_texts = [build_rich_text(p) for p in products]

    # Apercu du premier texte pour vérification
    if total > 0:
        print(f"   ex: {rich_texts[0][:120]}")

    # 5. Générer les embeddings en batches
    print(f"🧠 Génération embeddings ({BATCH_SIZE} par batch) …")
    t_emb = time.time()
    embeddings = model.encode(
        rich_texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    print(f"   ✓ {total} embeddings générés en {time.time()-t_emb:.1f}s")

    # 6. Upsert dans Supabase
    ok = 0
    errors = 0
    for i, (product, embedding, rich_text) in enumerate(zip(products, embeddings, rich_texts)):
        pid       = product["id"]
        emb_list  = embedding.tolist()

        if args.dry_run:
            print(f"  [DRY-RUN] {product['name']} → dim={len(emb_list)}")
            ok += 1
            continue

        try:
            sb_patch(f"products?id=eq.{pid}", {
                "embedding": emb_list,
                "embedding_text": rich_text,
            })
            ok += 1
            if (i + 1) % 10 == 0 or i == total - 1:
                print(f"  [{i+1}/{total}] ✓")
        except Exception as e:
            errors += 1
            print(f"  [{i+1}/{total}] ❌ {product['name']}: {e}")

    print(f"\n{'🎉' if errors == 0 else '⚠️'} Terminé : {ok} OK, {errors} erreurs")
    if not args.dry_run:
        print("\n💡 Prochaine étape : redémarre le serveur Next.js pour activer la recherche vectorielle.")


if __name__ == "__main__":
    main()
