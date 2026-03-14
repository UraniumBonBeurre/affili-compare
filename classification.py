#!/usr/bin/env python3
"""
classification.py — Classification LLM des produits via la taxonomie
=====================================================================

Pour chaque produit non classifié, appelle le LLM pour déterminer :
  - llm_product_type, llm_category, llm_niche

La taxonomie est définie dans config/taxonomy/ (categories.json + niche_product_types.json).
Le LLM utilisé est CLASSIFICATION_LLM (settings.py).

Usage :
    python3 classification.py                    # Classer les non-classifiés
    python3 classification.py --force            # Re-classifier tout
    python3 classification.py --merchant imou_fr # Un seul marchand
    python3 classification.py --limit 100        # Limiter
    python3 classification.py --dry-run          # Simuler
"""

import argparse
import concurrent.futures
import math
import threading
import json
import re
import sys
import time
from pathlib import Path

import requests
import random

from settings import (
    SUPABASE_URL, SUPABASE_KEY, GOOGLE_AI_API_KEY, GOOGLE_AI_MODEL,
    sb_headers, check_supabase,
)

# ── Config LLM ────────────────────────────────────────────────────────────────
PAGE_SIZE          = 1000
DEFAULT_BATCH_SIZE = 500   # produits/batch Gemini (compact encoding)
MAX_DESC_LEN       = 200
LLM_RETRY_MAX      = 3
GEMINI_CONCURRENT  = 4     # workers parallèles
GEMINI_BACKOFF     = {429: [10, 20, 40], 503: [5, 10, 20]}

# ── Token bucket rate limiter ─────────────────────────────────────────────────
# Espace les requêtes dès le départ — ne dépend pas d'un premier 429 pour freiner
GEMINI_RPM    = 8           # 8 req/min max → ~7.5s entre requêtes (ajuster si encore 429)
_rl_lock      = threading.Lock()
_rl_next_slot = 0.0         # heure (time.time()) à partir de laquelle la prochaine req peut partir


def _rl_acquire() -> None:
    """Réserve un slot de requête ; attend si nécessaire pour rester sous GEMINI_RPM."""
    global _rl_next_slot
    interval = 60.0 / GEMINI_RPM
    while True:
        with _rl_lock:
            now = time.time()
            if now >= _rl_next_slot:
                _rl_next_slot = now + interval
                return
            wait = _rl_next_slot - now
        time.sleep(wait)


def _rl_punish(extra: float) -> None:
    """Après un 429/503, repousse le prochain slot de `extra` secondes."""
    global _rl_next_slot
    with _rl_lock:
        _rl_next_slot = max(_rl_next_slot, time.time()) + extra
    print(f"  🛑  Rate limit → prochain slot dans {extra:.0f}s", flush=True)

# ── Taxonomie ─────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).parent

def _load_categories() -> list:
    p = _ROOT / "config" / "taxonomy" / "categories.json"
    if not p.exists():
        print(f"❌  Taxonomy introuvable : {p}")
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))["categories"]


def _load_niche_product_types() -> dict:
    p = _ROOT / "config" / "taxonomy" / "niche_product_types.json"
    if not p.exists():
        print(f"❌  Taxonomy introuvable : {p}")
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


CATEGORIES_DATA     = _load_categories()
NICHE_PRODUCT_TYPES = _load_niche_product_types()  # {niche_slug: [{id, name_fr, name_en}]}

CATEGORIES_LIST = [c["id"] for c in CATEGORIES_DATA]
NICHES_LIST     = [n["slug"] for c in CATEGORIES_DATA for n in c["niches"]]
NICHE_TYPES_ORDERED = {slug: types for slug, types in NICHE_PRODUCT_TYPES.items()}

VALID_CATEGORIES = set(CATEGORIES_LIST)
VALID_NICHES     = set(NICHES_LIST)
VALID_TYPES_BY_NICHE: dict[str, set[str]] = {
    slug: {t["id"] for t in types} | {"autre"}
    for slug, types in NICHE_TYPES_ORDERED.items()
}


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

def _build_user_message(products: list[dict]) -> tuple[str, list[str]]:
    """Returns (JSON string, id_map) — i est un index entier léger en entrée."""
    id_map = [str(p["id"]) for p in products]
    mini = []
    for idx, p in enumerate(products):
        desc = (p.get("description") or "")[:MAX_DESC_LEN]
        entry: dict = {
            "i": idx,
            "name": p.get("name") or "",
            "brand": p.get("brand") or "",
            "merchant_category": p.get("merchant_category") or "",
            "description": desc,
        }
        awin_cat = p.get("awin_category") or ""
        if awin_cat:
            entry["awin_category"] = awin_cat
        mini.append(entry)
    return json.dumps(mini, ensure_ascii=False), id_map


def _build_slug_system_prompt() -> str:
    """Prompt slug-based : le LLM retourne directement les ids, sans mapping numérique."""
    lines = [
        "Classifie chaque produit e-commerce dans la taxonomie ci-dessous.",
        'Retourne UNIQUEMENT ce JSON compact :',
        '{"results":[{"i":N,"c":"cat-id","n":"niche-slug","t":"type-id"}]}',
        "",
        "i = index du produit (entier, repris tel quel)",
        "c = id de la catégorie (exactement comme listé ci-dessous)",
        "n = slug de la niche (doit appartenir à la catégorie c)",
        't = id du type de produit (parmi ceux listés pour la niche n, ou "autre" si aucun ne convient)',
        "",
        "TAXONOMIE :",
    ]
    for cat in CATEGORIES_DATA:
        lines.append(f"\n[{cat['id']}]  {cat['name']}")
        for niche in cat["niches"]:
            nslug = niche["slug"]
            types = NICHE_TYPES_ORDERED.get(nslug, [])
            type_ids = "  ".join(t["id"] for t in types)
            lines.append(f"  {nslug}: {type_ids}")
    return "\n".join(lines)


def _extract_partial_items(raw: str) -> list:
    """Extraction regex des items quand le JSON global est invalide (JSON tronqué, caractère non échappé…)."""
    pattern = r'\{\s*"i"\s*:\s*(\d+)\s*,\s*"c"\s*:\s*"([^"\\]*)"\s*,\s*"n"\s*:\s*"([^"\\]*)"\s*,\s*"t"\s*:\s*"([^"\\]*)"\s*\}'
    return [{"i": int(i), "c": c, "n": n, "t": t} for i, c, n, t in re.findall(pattern, raw)]


def _parse_slug_response(raw: str, id_map: list[str]) -> list[dict]:
    """Parse la réponse slug-based. Valide chaque champ contre la taxonomie."""
    try:
        raw = raw.strip()
        start = raw.find("{")
        if start == -1:
            raise ValueError("Pas de JSON")
        data, _ = json.JSONDecoder().raw_decode(raw[start:])
        items = data.get("results", [])
    except (json.JSONDecodeError, ValueError) as e:
        print(f"    ⚠️  Parse JSON échoué: {e} — extraction partielle par regex")
        items = _extract_partial_items(raw)
        if not items:
            return []
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("i", -1))
        except (ValueError, TypeError):
            continue
        if not (0 <= idx < len(id_map)):
            continue
        cat   = str(item.get("c", "")).strip()
        niche = str(item.get("n", "")).strip()
        ptype = str(item.get("t", "autre")).strip()
        if cat   not in VALID_CATEGORIES: cat   = CATEGORIES_LIST[0]
        if niche not in VALID_NICHES:     niche = NICHES_LIST[0]
        if ptype not in VALID_TYPES_BY_NICHE.get(niche, {"autre"}): ptype = "autre"
        results.append({"id": id_map[idx], "category": cat, "niche": niche, "product_type": ptype})
    return results


# ── LLM backends ─────────────────────────────────────────────────────────────

def _call_gemini(system: str, user: str, batch_id: int = 0, t0: float = None) -> str | None:
    if t0 is None:
        t0 = time.time()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{GOOGLE_AI_MODEL}"
        f":generateContent?key={GOOGLE_AI_API_KEY}"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0,
            "maxOutputTokens": 65536,
        },
    }
    max_http_retries = len(GEMINI_BACKOFF[429])
    for attempt in range(max_http_retries + 1):
        _rl_acquire()  # espace les requêtes selon GEMINI_RPM
        r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=120)
        if r.status_code in GEMINI_BACKOFF and attempt < max_http_retries:
            elapsed_so_far = round(time.time() - t0, 2)
            extra = 60.0 if r.status_code == 429 else 10.0
            _rl_punish(extra)
            print(f"  ⚠️   batch {batch_id:02d}  HTTP {r.status_code}  tentative {attempt+1}/{max_http_retries}"
                  f"  ({elapsed_so_far}s écoulé)")
            continue
        if r.status_code != 200:
            print(f"  ⚠️   batch {batch_id:02d}  HTTP {r.status_code}: {r.text[:200]}")
            return None
        try:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            print(f"  ⚠️   batch {batch_id:02d}  réponse Gemini inattendue: {e}")
            return None
    return None


# ── Parser ────────────────────────────────────────────────────────────────────

def classify_batch(products: list[dict], system: str, batch_id: int = 0) -> list[dict]:
    t0 = time.time()
    user_msg, id_map = _build_user_message(products)
    for attempt in range(1, LLM_RETRY_MAX + 1):
        raw = _call_gemini(system, user_msg, batch_id=batch_id, t0=t0)
        if raw is None:
            if attempt < LLM_RETRY_MAX:
                time.sleep(60)
            continue
        parsed = _parse_slug_response(raw, id_map)
        if len(parsed) >= len(products) * 0.5:
            elapsed = round(time.time() - t0, 2)
            retry_tag = f"  [retry ×{attempt-1}]" if attempt > 1 else ""
            print(f"  ✅  batch {batch_id:02d}  ✓{len(parsed)}/{len(products)}  {elapsed}s{retry_tag}")
            return parsed
        if attempt < LLM_RETRY_MAX:
            print(f"  ↺   batch {batch_id:02d}  parse partiel {len(parsed)}/{len(products)} → retry {attempt+1}/{LLM_RETRY_MAX}")
            time.sleep(2)
    elapsed = round(time.time() - t0, 2)
    print(f"  ❌  batch {batch_id:02d}  échoué après {LLM_RETRY_MAX} tentatives  {elapsed}s")
    return []


# ── Main ──────────────────────────────────────────────────────────────────────

def _export_classifications_to_csv(products: list[dict], csv_path: str) -> None:
    """Export classified products to CSV with columns: name, brand, description, llm_niche."""
    import csv

    if not products:
        print("  ⚠️  Aucun produit à exporter")
        return

    product_ids = [p["id"] for p in products]
    print(f"\n  📝  Fetching classifications from DB for export…")

    all_classified = []
    for chunk_idx in range(0, len(product_ids), 100):
        chunk = product_ids[chunk_idx:chunk_idx + 100]
        id_filter = ",".join(f'"{id_str}"' for id_str in chunk)
        params = f"id=in.({id_filter})&select=id,name,brand,description,llm_niche"
        page = sb_get("products", params)
        all_classified.extend(page)

    exported = []
    for prod in all_classified:
        niche = prod.get("llm_niche") or ""
        if niche:
            exported.append({
                "name": prod.get("name", ""),
                "brand": prod.get("brand", ""),
                "description": (prod.get("description") or "")[:500],
                "niche": niche,
            })

    csv_path_obj = Path(csv_path)
    csv_path_obj.parent.mkdir(parents=True, exist_ok=True)

    with open(csv_path_obj, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "brand", "description", "niche"])
        writer.writeheader()
        writer.writerows(exported)

    print(f"  ✅  Exported {len(exported)}/{len(all_classified)} classified products to {csv_path}")


def main():
    parser = argparse.ArgumentParser(description="Classifie les produits via LLM")
    parser.add_argument("--force", action="store_true", help="Re-classifier tout")
    parser.add_argument("--merchant", type=str, default=None, help="Limiter à un merchant_key")
    parser.add_argument("--limit", type=int, default=None, help="Nombre max de produits")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help=f"Défaut: {DEFAULT_BATCH_SIZE}")
    parser.add_argument("--dry-run", action="store_true", help="Pas d'écriture DB")
    parser.add_argument("--export-csv", type=str, default=None,
                        help="Exporter les résultats classifiés dans un CSV [name, brand, description, niche]")
    args = parser.parse_args()

    check_supabase()

    _model_label = GOOGLE_AI_MODEL
    print(f"\n{'═'*62}")
    print(f"  🤖  classification.py — LLM: {_model_label}")
    print(f"  Taxonomie: {len(CATEGORIES_LIST)} catégories · {len(NICHES_LIST)} niches · {sum(len(v) for v in NICHE_TYPES_ORDERED.values())} types configurés")
    print(f"  Batch: {args.batch_size}  |  Force: {'oui' if args.force else 'non'}")
    if args.dry_run: print("  Mode DRY-RUN")
    print(f"{'═'*62}\n")

    system_prompt = _build_slug_system_prompt()

    # Récupérer les produits
    all_products: list[dict] = []
    offset = 0
    base_filter = "active=not.is.false"
    if not args.force:
        base_filter += "&llm_category=is.null"
    if args.merchant:
        base_filter += f"&merchant_key=eq.{args.merchant}"

    print("🔍  Récupération des produits…")
    while True:
        params = (
            f"{base_filter}"
            "&select=id,name,brand,category_slug,merchant_category,awin_category,merchant_key,description"
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

    n_batches = math.ceil(len(all_products) / args.batch_size)
    batches   = [all_products[i * args.batch_size:(i + 1) * args.batch_size]
                 for i in range(n_batches)]
    total_classified = 0
    total_written    = 0
    t_start = time.time()

    def _write_classifications(classifications: list[dict]) -> None:
        nonlocal total_classified, total_written
        if not classifications:
            return
        upsert_rows = [{
            "id": c["id"],
            "llm_product_type": c["product_type"],
            "llm_category":     c["category"],
            "llm_niche":        c["niche"],
        } for c in classifications]
        if args.dry_run:
            for r in upsert_rows[:2]:
                print(f"     [DRY] {str(r['id'])[:8]}… → {r['llm_product_type']} | {r['llm_category']} / {r['llm_niche']}")
        else:
            written = sb_patch_batch(upsert_rows, dry_run=False)
            total_written += written
        total_classified += len(classifications)

    # ── Exécution parallèle 4 workers + encodage compact ────────────────────
    n_success = 0
    lock = threading.Lock()

    print(f"▶  {len(all_products)} produits  ·  {n_batches} batches de ~{args.batch_size}  ·  {GEMINI_CONCURRENT} workers en parallèle")
    print(f"   Retry : jusqu'à {LLM_RETRY_MAX}× par batch (backoff 429={GEMINI_BACKOFF[429]}, 503={GEMINI_BACKOFF[503]})\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=GEMINI_CONCURRENT) as ex:
        futures = {ex.submit(classify_batch, b, system_prompt, i): i
                   for i, b in enumerate(batches)}
        for fut in concurrent.futures.as_completed(futures):
            classifications = fut.result()
            with lock:
                _write_classifications(classifications)
                if classifications:
                    n_success += 1

    total_elapsed = round(time.time() - t_start, 2)
    throughput = round(total_classified / total_elapsed) if total_elapsed > 0 else 0

    print(f"\n{'═'*60}")
    print(f"  Batches réussis : {n_success}/{n_batches}")
    print(f"  Produits ok     : {total_classified}/{len(all_products)} ({round(100*total_classified/max(len(all_products),1))}%)")
    print(f"  Écrits DB       : {total_written}")
    print(f"  Temps total     : {total_elapsed}s")
    print(f"  Débit           : {throughput} produits/s")
    print(f"{'═'*60}\n")

    if args.export_csv and not args.dry_run:
        _export_classifications_to_csv(all_products, args.export_csv)


if __name__ == "__main__":
    main()
