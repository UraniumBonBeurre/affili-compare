#!/usr/bin/env python3
"""
classification.py — Classification LLM des produits via la taxonomie
=====================================================================

Pour chaque produit non classifié, appelle le LLM pour déterminer :
  - llm_product_type, llm_room, llm_use_category, llm_niches

La taxonomie est définie dans config/product_taxonomy.json.
Le LLM utilisé est CLASSIFICATION_LLM (settings.py).

Usage :
    python3 scripts/classification.py                    # Classer les non-classifiés
    python3 scripts/classification.py --force            # Re-classifier tout
    python3 scripts/classification.py --merchant imou_fr # Un seul marchand
    python3 scripts/classification.py --limit 100        # Limiter
    python3 scripts/classification.py --dry-run          # Simuler
"""

import argparse
import concurrent.futures
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from settings import (
    SUPABASE_URL, SUPABASE_KEY, GOOGLE_AI_API_KEY, GOOGLE_AI_MODEL,
    OLLAMA_CLOUD_API_KEY, OLLAMA_CLOUD_HOST, OLLAMA_CLOUD_MODEL,
    TAXONOMY_PATH, CLASSIFICATION_LLM, sb_headers, check_supabase,
)

# ── Config LLM ────────────────────────────────────────────────────────────────
PAGE_SIZE = 1000
DEFAULT_BATCH_SIZE = 150
MAX_DESC_LEN = 200
LLM_RETRY_MAX = 3
LLM_SLEEP_BETWEEN = 0.3

# Priorité : Google AI > Ollama
if GOOGLE_AI_API_KEY:
    LLM_BACKEND = "gemini"
else:
    LLM_BACKEND = "ollama"

# ── Taxonomie ─────────────────────────────────────────────────────────────────

def _load_taxonomy() -> dict:
    if not TAXONOMY_PATH.exists():
        print(f"❌  Taxonomie introuvable : {TAXONOMY_PATH}")
        sys.exit(1)
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


TAXONOMY = _load_taxonomy()
VALID_PRODUCT_TYPES = set(TAXONOMY["product_types"].keys())
VALID_ROOMS = set(TAXONOMY["rooms"].keys())
VALID_USE_CATEGORIES = set(TAXONOMY["use_categories"].keys())
VALID_NICHES = set(TAXONOMY["niches"].keys())


# ── Supabase ──────────────────────────────────────────────────────────────────

def sb_get(path: str, params: str = "") -> list:
    url = f"{SUPABASE_URL}/rest/v1/{path}{'?' + params if params else ''}"
    r = requests.get(url, headers=sb_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def _patch_one(row: dict) -> bool:
    prod_id = row["id"]
    payload = {k: v for k, v in row.items() if k != "id"}
    try:
        r = requests.patch(
            f"{SUPABASE_URL}/rest/v1/products?id=eq.{prod_id}",
            headers=sb_headers({"Prefer": "return=minimal"}),
            json=payload, timeout=15,
        )
        return r.status_code in (200, 204)
    except Exception:
        return False


def sb_patch_batch(rows: list[dict], dry_run: bool = False) -> int:
    if not rows:
        return 0
    if dry_run:
        return len(rows)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(_patch_one, rows))
    failed = sum(1 for r in results if not r)
    if failed:
        print(f"  ⚠️  {failed}/{len(rows)} PATCH échoués")
    return sum(1 for r in results if r)


# ── Prompt ────────────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    pt_list = ", ".join(VALID_PRODUCT_TYPES)
    rm_list = ", ".join(VALID_ROOMS)
    uc_list = ", ".join(VALID_USE_CATEGORIES)
    ni_items = "\n".join(f"  {k}: {v}" for k, v in TAXONOMY["niches"].items())

    return f"""Tu es un classificateur de produits e-commerce français spécialisé en tech et maison connectée.
Pour chaque produit de la liste JSON fournie, tu dois retourner une classification structurée.

TAXONOMIE :

product_type (choisir EXACTEMENT 1 clé parmi) :
{pt_list}

room (choisir EXACTEMENT 1 clé parmi) :
{rm_list}

use_category (choisir EXACTEMENT 1 clé parmi) :
{uc_list}

niches (liste de 0 à 4 clés parmi ces niches lifestyle Pinterest) :
{ni_items}

RÈGLES :
- product_type : si aucun ne correspond parfaitement, utilise "autre"
- room : choisir la pièce où le produit est LE PLUS souvent utilisé
- niches : un produit n'appartient à une niche que s'il y serait réellement recommandé dans un article Pinterest "Top 5 incontournables". Ex: une licence logicielle → niches=[]
- Un produit peut être dans plusieurs niches (max 4), mais sois sélectif
- Si les infos sont insuffisantes, utilise les valeurs les plus génériques ("universel", "accessoire")

FORMAT DE RÉPONSE (JSON strict, AUCUN texte en dehors) :
{{"results": [{{"id": "ID_PRODUIT", "product_type": "clé", "room": "clé", "use_category": "clé", "niches": ["clé1", "clé2"]}}]}}"""


def _build_user_message(products: list[dict]) -> str:
    mini = []
    for p in products:
        desc = (p.get("description") or "")[:MAX_DESC_LEN]
        mini.append({
            "id": str(p["id"]),
            "name": p.get("name") or "",
            "brand": p.get("brand") or "",
            "category_slug": p.get("category_slug") or "",
            "merchant_category": p.get("merchant_category") or "",
            "description": desc,
        })
    return json.dumps(mini, ensure_ascii=False)


# ── LLM backends ─────────────────────────────────────────────────────────────

def _call_gemini(system: str, user: str) -> str | None:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{GOOGLE_AI_MODEL}"
        f":generateContent?key={GOOGLE_AI_API_KEY}"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=120)
    if r.status_code != 200:
        print(f"    ⚠️  Gemini HTTP {r.status_code}: {r.text[:300]}")
        return None
    try:
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        print(f"    ⚠️  Réponse Gemini inattendue: {e}")
        return None


def _call_ollama(system: str, user: str) -> str | None:
    r = requests.post(
        f"{OLLAMA_CLOUD_HOST}/api/chat",
        headers={"Authorization": f"Bearer {OLLAMA_CLOUD_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": OLLAMA_CLOUD_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "think": False,
        },
        timeout=600,
    )
    if r.status_code != 200:
        print(f"    ⚠️  Ollama HTTP {r.status_code}: {r.text[:200]}")
        return None
    data = r.json()
    if "message" in data:
        return data["message"].get("content", "")
    return data.get("response", "")


def _call_llm(system: str, user: str) -> str | None:
    if LLM_BACKEND == "gemini":
        return _call_gemini(system, user)
    return _call_ollama(system, user)


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse_response(raw: str, products: list[dict]) -> list[dict]:
    product_ids = {str(p["id"]) for p in products}
    results = []
    try:
        raw = raw.strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("Pas de JSON trouvé")
        data = json.loads(raw[start:end])
        items = data.get("results", [])
    except (json.JSONDecodeError, ValueError) as e:
        print(f"    ⚠️  Parse JSON échoué: {e}")
        return []

    for item in items:
        pid = str(item.get("id", ""))
        if pid not in product_ids:
            continue

        pt = item.get("product_type", "autre")
        rm = item.get("room", "universel")
        uc = item.get("use_category", "accessoire")
        ni = item.get("niches", [])

        if pt not in VALID_PRODUCT_TYPES: pt = "autre"
        if rm not in VALID_ROOMS: rm = "universel"
        if uc not in VALID_USE_CATEGORIES: uc = "accessoire"
        if not isinstance(ni, list): ni = []
        ni = [n for n in ni if n in VALID_NICHES][:4]

        results.append({"id": pid, "product_type": pt, "room": rm, "use_category": uc, "niches": ni})

    return results


def classify_batch(products: list[dict], system: str) -> list[dict]:
    user_msg = _build_user_message(products)
    for attempt in range(1, LLM_RETRY_MAX + 1):
        raw = _call_llm(system, user_msg)
        if raw is None:
            if attempt < LLM_RETRY_MAX:
                time.sleep(2 ** attempt)
            continue
        parsed = _parse_response(raw, products)
        if len(parsed) >= len(products) * 0.5:
            return parsed
        print(f"    ↺  Tentative {attempt}/{LLM_RETRY_MAX} — {len(parsed)}/{len(products)} résultats")
        if attempt < LLM_RETRY_MAX:
            time.sleep(2)
    print(f"  ⚠️  Batch échoué après {LLM_RETRY_MAX} tentatives")
    return []


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Classifie les produits via LLM")
    parser.add_argument("--force", action="store_true", help="Re-classifier tout")
    parser.add_argument("--merchant", type=str, default=None, help="Limiter à un merchant_key")
    parser.add_argument("--limit", type=int, default=None, help="Nombre max de produits")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help=f"Défaut: {DEFAULT_BATCH_SIZE}")
    parser.add_argument("--dry-run", action="store_true", help="Pas d'écriture DB")
    args = parser.parse_args()

    check_supabase()

    _model_label = f"{GOOGLE_AI_MODEL} (Google AI)" if LLM_BACKEND == "gemini" else OLLAMA_CLOUD_MODEL
    print(f"\n{'═'*62}")
    print(f"  🤖  classification.py — LLM: {LLM_BACKEND.upper()} ({_model_label})")
    print(f"  Batch: {args.batch_size}  |  Force: {'oui' if args.force else 'non'}")
    if args.dry_run: print("  Mode DRY-RUN")
    print(f"{'═'*62}\n")

    system_prompt = _build_system_prompt()

    # Récupérer les produits
    all_products: list[dict] = []
    offset = 0
    base_filter = "active=not.is.false"
    if not args.force:
        base_filter += "&llm_classified_at=is.null"
    if args.merchant:
        base_filter += f"&merchant_key=eq.{args.merchant}"

    print("🔍  Récupération des produits…")
    while True:
        params = (
            f"{base_filter}"
            "&select=id,name,brand,category_slug,merchant_category,description"
            f"&order=id.asc&limit={PAGE_SIZE}&offset={offset}"
        )
        page = sb_get("products", params)
        if not page:
            break
        all_products.extend(page)
        offset += len(page)
        if args.limit and len(all_products) >= args.limit:
            all_products = all_products[:args.limit]
            break
        if len(page) < PAGE_SIZE:
            break

    print(f"  ✅  {len(all_products)} produits à classifier")
    if not all_products:
        print("  ℹ️  Rien à faire")
        return

    # Classifier par batches
    total_classified = 0
    total_written = 0
    n_batches = (len(all_products) + args.batch_size - 1) // args.batch_size

    for batch_idx in range(n_batches):
        start = batch_idx * args.batch_size
        batch = all_products[start:start + args.batch_size]
        print(f"\n  📦  Batch {batch_idx + 1}/{n_batches} ({len(batch)} produits)…")

        classifications = classify_batch(batch, system_prompt)
        if not classifications:
            continue

        now_iso = datetime.now(timezone.utc).isoformat()
        upsert_rows = [{
            "id": c["id"],
            "llm_product_type": c["product_type"],
            "llm_room": c["room"],
            "llm_use_category": c["use_category"],
            "llm_niches": c["niches"],
            "llm_classified_at": now_iso,
        } for c in classifications]

        if args.dry_run:
            for r in upsert_rows[:3]:
                print(f"     [DRY] {r['id'][:8]}… → {r['llm_product_type']} | {r['llm_niches']}")
        else:
            for r in upsert_rows[:2]:
                print(f"     ✓ {str(r['id'])[:8]}… → {r['llm_product_type']} | niches: {r['llm_niches']}")

        written = sb_patch_batch(upsert_rows, dry_run=args.dry_run)
        total_classified += len(classifications)
        total_written += written

        if not args.dry_run:
            time.sleep(LLM_SLEEP_BETWEEN)

    print(f"\n{'═'*62}")
    print(f"  ✅  {total_classified}/{len(all_products)} classifiés, {total_written} écrits DB")
    print(f"{'═'*62}\n")


if __name__ == "__main__":
    main()
