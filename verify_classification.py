#!/usr/bin/env python3
"""
verify_classification.py — Vérification LLM des classifications existantes
==========================================================================

Pour chaque produit déjà classifié, demande au LLM de vérifier la classification.
3 verdicts possibles :
  - ok     : classification confirmée (aucune action)
  - move   : LLM certain d'un meilleur chemin (mise à jour DB automatique)
  - unsure : LLM hésite entre plusieurs chemins → écrit dans config/verify_pending.json

Les lignes PROGRESS:... et DONE:... sont émises sur stdout pour le dashboard SSE.

Usage :
    python3 verify_classification.py
    python3 verify_classification.py --limit 500
    python3 verify_classification.py --batch-size 200
    python3 verify_classification.py --dry-run
"""

import argparse
import concurrent.futures
import json
import math
import random
import re
import threading
import time
from pathlib import Path

import requests

from settings import (
    SUPABASE_URL, GOOGLE_AI_API_KEY, GOOGLE_AI_MODEL,
    sb_headers, check_supabase,
)

# ── Config ────────────────────────────────────────────────────────────────────
PAGE_SIZE          = 1000
DEFAULT_BATCH_SIZE = 200
MAX_DESC_LEN       = 150
LLM_RETRY_MAX      = 3
GEMINI_CONCURRENT  = 4
GEMINI_BACKOFF     = {429: [10, 20, 40], 503: [5, 10, 20]}
PENDING_PATH       = Path(__file__).parent / "config" / "verify_pending.json"

# ── Token bucket rate limiter ─────────────────────────────────────────────────
GEMINI_RPM    = 8
_rl_lock      = threading.Lock()
_rl_next_slot = 0.0


def _rl_acquire() -> None:
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
    global _rl_next_slot
    with _rl_lock:
        _rl_next_slot = max(_rl_next_slot, time.time()) + extra
    print(f"  🛑  Rate limit → prochain slot dans {extra:.0f}s", flush=True)

# ── Taxonomie ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent


def _load_categories() -> list:
    p = _ROOT / "config" / "taxonomy" / "categories.json"
    if not p.exists():
        print(f"❌  Taxonomy introuvable : {p}", flush=True)
        raise SystemExit(1)
    return json.loads(p.read_text(encoding="utf-8"))["categories"]


def _load_niche_product_types() -> dict:
    p = _ROOT / "config" / "taxonomy" / "niche_product_types.json"
    if not p.exists():
        print(f"❌  Taxonomy introuvable : {p}", flush=True)
        raise SystemExit(1)
    return json.loads(p.read_text(encoding="utf-8"))


CATEGORIES_DATA     = _load_categories()
NICHE_PRODUCT_TYPES = _load_niche_product_types()
CATEGORIES_LIST     = [c["id"] for c in CATEGORIES_DATA]
NICHES_LIST         = [n["slug"] for c in CATEGORIES_DATA for n in c["niches"]]
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(_patch_one, rows))
    failed = sum(1 for r in results if not r)
    if failed:
        print(f"  ⚠️  {failed}/{len(rows)} PATCH échoués", flush=True)
    return sum(1 for r in results if r)


# ── System prompt ─────────────────────────────────────────────────────────────

def _build_verify_system_prompt() -> str:
    """Prompt slug-based : le LLM retourne directement les ids, sans mapping numérique."""
    lines = [
        "Vérifie la classification actuelle de chaque produit e-commerce.",
        "Chaque item contient son chemin actuel (cur_c, cur_n, cur_t).",
        "Retourne UNIQUEMENT ce JSON compact :",
        '{"results":[{"i":N,"v":"ok"} | {"i":N,"v":"move","c":"cat-id","n":"niche-slug","t":"type-id"} | {"i":N,"v":"unsure","alts":[{"c":"cat-id","n":"niche-slug","t":"type-id"},...]}]}',
        "",
        'v="ok"     : chemin actuel correct, ne rien changer',
        'v="move"   : certain qu\'un autre chemin est meilleur (fournir c, n, t)',
        'v="unsure" : hésite entre au moins 2 chemins plausibles (fournir alts)',
        "c = id catégorie, n = slug niche, t = id type (ou \"autre\")",
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


# ── User message builder ──────────────────────────────────────────────────────

def _build_verify_user_message(products: list[dict]) -> tuple[str, list[str]]:
    """Inclut le chemin actuel en slugs — le LLM raisonne directement sans mapping."""
    id_map = [str(p["id"]) for p in products]
    mini = []
    for idx, p in enumerate(products):
        desc = (p.get("description") or "")[:MAX_DESC_LEN]
        mini.append({
            "i":     idx,
            "name":  p.get("name") or "",
            "brand": p.get("brand") or "",
            "desc":  desc,
            "cur_c": p.get("llm_category") or "",
            "cur_n": p.get("llm_niche") or "",
            "cur_t": p.get("llm_product_type") or "",
        })
    return json.dumps(mini, ensure_ascii=False), id_map


# ── Response decoder ──────────────────────────────────────────────────────────

def _decode_slug_path(c, n, t) -> dict | None:
    """Valide et enrichit un chemin slug-based. Retourne None si invalide."""
    cat_slug   = str(c or "").strip()
    niche_slug = str(n or "").strip()
    type_id    = str(t or "autre").strip()
    if cat_slug not in VALID_CATEGORIES or niche_slug not in VALID_NICHES:
        return None
    if type_id not in VALID_TYPES_BY_NICHE.get(niche_slug, {"autre"}):
        type_id = "autre"
    cat_name   = next((ci["name"] for ci in CATEGORIES_DATA if ci["id"] == cat_slug), cat_slug)
    niche_name = next(
        (ni["name"] for ci in CATEGORIES_DATA for ni in ci["niches"] if ni["slug"] == niche_slug),
        niche_slug,
    )
    types      = NICHE_TYPES_ORDERED.get(niche_slug, [])
    type_name  = next((tp["name_fr"] for tp in types if tp["id"] == type_id), type_id)
    return {
        "category":     {"id": cat_slug,    "name":    cat_name},
        "niche":        {"slug": niche_slug, "name":   niche_name},
        "product_type": {"id": type_id,     "name_fr": type_name},
    }


def _extract_partial_verify_items(raw: str) -> list:
    """Extraction regex des items quand le JSON global est invalide."""
    results = []
    # ok items: {"i":N,"v":"ok"}
    for m in re.finditer(r'\{\s*"i"\s*:\s*(\d+)\s*,\s*"v"\s*:\s*"ok"\s*\}', raw):
        results.append({"i": int(m.group(1)), "v": "ok"})
    # move items: {"i":N,"v":"move","c":"...","n":"...","t":"..."}
    pat_move = r'\{\s*"i"\s*:\s*(\d+)\s*,\s*"v"\s*:\s*"move"\s*,\s*"c"\s*:\s*"([^"\\]*)"\s*,\s*"n"\s*:\s*"([^"\\]*)"\s*,\s*"t"\s*:\s*"([^"\\]*)"\s*\}'
    for m in re.finditer(pat_move, raw):
        results.append({"i": int(m.group(1)), "v": "move", "c": m.group(2), "n": m.group(3), "t": m.group(4)})
    return results


def _parse_verify_response(
    raw: str, id_map: list[str], products: list[dict]
) -> tuple[list[str], list[dict], list[dict]]:
    """Returns (ok_ids, move_rows, unsure_items). Réponse slug-based."""
    try:
        raw = raw.strip()
        start = raw.find("{")
        if start == -1:
            raise ValueError("Pas de JSON")
        data, _ = json.JSONDecoder().raw_decode(raw[start:])
        items = data.get("results", [])
    except Exception as e:
        print(f"    ⚠️  Parse JSON échoué: {e} — extraction partielle par regex", flush=True)
        items = _extract_partial_verify_items(raw)
        if not items:
            return [], [], []

    ok_ids    = []
    move_rows = []
    unsure    = []

    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("i", -1))
        except (ValueError, TypeError):
            continue
        if not (0 <= idx < len(id_map)):
            continue

        prod_id = id_map[idx]
        prod    = products[idx]
        verdict = item.get("v", "ok")

        if verdict == "ok":
            ok_ids.append(prod_id)

        elif verdict == "move":
            path = _decode_slug_path(item.get("c"), item.get("n"), item.get("t"))
            if path:
                move_rows.append({
                    "id":               prod_id,
                    "llm_category":     path["category"]["id"],
                    "llm_niche":        path["niche"]["slug"],
                    "llm_product_type": path["product_type"]["id"],
                })

        elif verdict == "unsure":
            alts_raw = item.get("alts", [])
            alts = [_decode_slug_path(a.get("c"), a.get("n"), a.get("t")) for a in alts_raw]
            alts = [a for a in alts if a]
            if len(alts) >= 2:
                unsure.append({
                    "product": {
                        "id":          prod_id,
                        "name":        prod.get("name") or "",
                        "brand":       prod.get("brand") or "",
                        "description": (prod.get("description") or "")[:300],
                    },
                    "current": {
                        "category_id": prod.get("llm_category") or "",
                        "niche_slug":  prod.get("llm_niche") or "",
                        "type_id":     prod.get("llm_product_type") or "",
                    },
                    "alts": alts,
                })

    return ok_ids, move_rows, unsure


# ── Gemini call ───────────────────────────────────────────────────────────────

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
    for attempt in range(len(GEMINI_BACKOFF[429]) + 1):
        _rl_acquire()
        r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=120)
        if r.status_code in GEMINI_BACKOFF and attempt < len(GEMINI_BACKOFF[r.status_code]):
            extra = 60.0 if r.status_code == 429 else 10.0
            _rl_punish(extra)
            print(f"  ⚠️  batch {batch_id:02d} HTTP {r.status_code} tentative {attempt+1}", flush=True)
            continue
        if r.status_code != 200:
            print(f"  ⚠️  batch {batch_id:02d} HTTP {r.status_code}: {r.text[:200]}", flush=True)
            return None
        try:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            print(f"  ⚠️  batch {batch_id:02d} réponse inattendue: {e}", flush=True)
            return None
    return None


# ── Batch worker ──────────────────────────────────────────────────────────────

def verify_batch(
    products: list[dict], system: str, batch_id: int = 0
) -> tuple[list[str], list[dict], list[dict]]:
    t0 = time.time()
    user_msg, id_map = _build_verify_user_message(products)
    for attempt in range(1, LLM_RETRY_MAX + 1):
        raw = _call_gemini(system, user_msg, batch_id=batch_id, t0=t0)
        if raw is None:
            if attempt < LLM_RETRY_MAX:
                time.sleep(60)
            continue
        ok_ids, move_rows, unsure = _parse_verify_response(raw, id_map, products)
        total_handled = len(ok_ids) + len(move_rows) + len(unsure)
        if total_handled >= len(products) * 0.5:
            elapsed   = round(time.time() - t0, 2)
            retry_tag = f"  [retry ×{attempt-1}]" if attempt > 1 else ""
            print(
                f"  ✅  batch {batch_id:02d}  ok={len(ok_ids)} move={len(move_rows)} unsure={len(unsure)}/{len(products)}  {elapsed}s{retry_tag}",
                flush=True,
            )
            return ok_ids, move_rows, unsure
        if attempt < LLM_RETRY_MAX:
            print(f"  ↺   batch {batch_id:02d}  partiel {total_handled}/{len(products)} → retry {attempt+1}", flush=True)
            time.sleep(2)
    elapsed = round(time.time() - t0, 2)
    print(f"  ❌  batch {batch_id:02d}  échec  {elapsed}s", flush=True)
    return [], [], []


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Vérifie les classifications LLM existantes")
    parser.add_argument("--limit",      type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--dry-run",    action="store_true")
    args = parser.parse_args()

    check_supabase()

    print(f"\n{'═'*62}", flush=True)
    print(f"  🔍  verify_classification.py — LLM: {GOOGLE_AI_MODEL}", flush=True)
    print(f"  Taxonomie: {len(CATEGORIES_LIST)} catégories · {len(NICHES_LIST)} niches · slug-based output", flush=True)
    if args.dry_run:
        print("  Mode DRY-RUN", flush=True)
    print(f"{'═'*62}\n", flush=True)

    system_prompt = _build_verify_system_prompt()

    # Fetch classified products
    all_products: list[dict] = []
    offset = 0
    base_filter = "active=not.is.false&llm_category=not.is.null"

    print("🔍  Récupération des produits classifiés…", flush=True)
    while True:
        params = (
            f"{base_filter}"
            "&select=id,name,brand,description,llm_category,llm_niche,llm_product_type"
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

    total = len(all_products)
    print(f"  ✅  {total} produits classifiés à vérifier", flush=True)
    if not total:
        print(f'DONE:{{"ok":0,"moved":0,"unsure":0,"total":0}}', flush=True)
        return

    n_batches = math.ceil(total / args.batch_size)
    batches   = [all_products[i * args.batch_size:(i + 1) * args.batch_size] for i in range(n_batches)]

    print(f"▶  {total} produits · {n_batches} batches de ~{args.batch_size} · {GEMINI_CONCURRENT} workers\n", flush=True)

    # Accumulators
    total_ok    = 0
    total_moved = 0
    all_unsure: list[dict] = []
    lock    = threading.Lock()
    t_start = time.time()

    def _process(batch_result: tuple) -> None:
        nonlocal total_ok, total_moved
        ok_ids, move_rows, unsure = batch_result
        with lock:
            total_ok    += len(ok_ids)
            total_moved += len(move_rows)
            all_unsure.extend(unsure)
            done_so_far  = total_ok + total_moved + len(all_unsure)
            print(
                f'PROGRESS:{{"ok":{total_ok},"moved":{total_moved},"unsure":{len(all_unsure)},"total":{total},"done":{done_so_far}}}',
                flush=True,
            )
        if move_rows and not args.dry_run:
            sb_patch_batch(move_rows)
        if args.dry_run and move_rows:
            for row in move_rows[:2]:
                print(f"  [DRY] {row['id'][:8]}… → {row['llm_category']} / {row['llm_niche']} / {row['llm_product_type']}", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=GEMINI_CONCURRENT) as ex:
        futures = {ex.submit(verify_batch, b, system_prompt, i): i for i, b in enumerate(batches)}
        for fut in concurrent.futures.as_completed(futures):
            _process(fut.result())

    # Save unsure to pending file (merge with existing)
    if all_unsure and not args.dry_run:
        PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict] = []
        if PENDING_PATH.exists():
            try:
                existing = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing_ids = {item["product"]["id"] for item in existing}
        new_items    = [item for item in all_unsure if item["product"]["id"] not in existing_ids]
        PENDING_PATH.write_text(
            json.dumps(existing + new_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    elapsed = round(time.time() - t_start, 2)
    print(f"\n{'═'*60}", flush=True)
    print(f"  ok     : {total_ok}/{total} ({round(100*total_ok/max(total,1))}%)", flush=True)
    print(f"  moved  : {total_moved}", flush=True)
    print(f"  unsure : {len(all_unsure)}", flush=True)
    print(f"  temps  : {elapsed}s", flush=True)
    print(f"{'═'*60}", flush=True)
    print(f'DONE:{{"ok":{total_ok},"moved":{total_moved},"unsure":{len(all_unsure)},"total":{total}}}', flush=True)


if __name__ == "__main__":
    main()
