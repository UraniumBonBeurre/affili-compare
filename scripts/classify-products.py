#!/usr/bin/env python3
"""
classify-products.py — Classification LLM en batch des produits Supabase
=========================================================================

Pour chaque produit de la table `products`, appelle un LLM pour déterminer :
  - llm_product_type   : type précis (ex: "camera_surveillance")
  - llm_room           : pièce principale d'usage (ex: "entree")
  - llm_use_category   : catégorie fonctionnelle (ex: "securite")
  - llm_niches         : liste de niches lifestyle compatibles

La taxonomie complète est définie dans config/product_taxonomy.json.

Backend LLM supportés (auto-détection par ordre de priorité) :
  1. OPENAI_API_KEY     → gpt-4o-mini (rapide, < 0.15 $/1M tokens, JSON strict)
  2. OLLAMA_CLOUD_API_KEY → minimax-m2.5:cloud (déjà utilisé dans le projet)

Commandes :
    # Classer tous les produits non encore classifiés
    python3 scripts/classify-products.py

    # Forcer la re-classification de tous les produits actifs
    python3 scripts/classify-products.py --force

    # Un seul marchand
    python3 scripts/classify-products.py --merchant imou_fr

    # Limiter le nombre de produits traités
    python3 scripts/classify-products.py --limit 100

    # Modifier la taille de batch LLM (défaut: 20)
    python3 scripts/classify-products.py --batch-size 30

    # Mode test : affiche ce qui serait fait sans écrire en DB
    python3 scripts/classify-products.py --dry-run --limit 20

Variables d'env (.env.local) :
    NEXT_PUBLIC_SUPABASE_URL     — URL Supabase
    SUPABASE_SERVICE_ROLE_KEY    — Clé service role
    OPENAI_API_KEY               — Clé OpenAI (recommandé : gpt-4o-mini)
    OLLAMA_CLOUD_API_KEY         — Alternative Ollama Cloud
    OLLAMA_CLOUD_HOST            — défaut: https://api.ollama.com
    OLLAMA_CLOUD_MODEL           — défaut: minimax-m2.5:cloud

Prérequis SQL (à appliquer dans Supabase Dashboard) :
    supabase/migrations/20260312_llm_taxonomy.sql
"""

import argparse
import concurrent.futures
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("❌  pip install requests")
    sys.exit(1)

# ── Chargement .env.local ──────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
for _env in (ROOT / ".env.local", ROOT / ".env"):
    if _env.exists():
        for _line in _env.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

# ── Config ────────────────────────────────────────────────────────────────────
SUPABASE_URL       = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY       = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY", "")
OLLAMA_API_KEY     = os.environ.get("OLLAMA_CLOUD_API_KEY", "")
OLLAMA_HOST        = os.environ.get("OLLAMA_CLOUD_HOST", "https://api.ollama.com")
OLLAMA_MODEL       = os.environ.get("OLLAMA_CLOUD_MODEL", "gemini-3-flash-preview:cloud")
GOOGLE_AI_API_KEY  = os.environ.get("GOOGLE_AI_API_KEY", "")
GOOGLE_AI_MODEL    = os.environ.get("GOOGLE_AI_MODEL", "gemini-2.0-flash")
TAXONOMY_PATH      = ROOT / "config" / "product_taxonomy.json"

PAGE_SIZE          = 1000   # produits récupérés par page Supabase
DEFAULT_BATCH_SIZE = 150    # produits par appel LLM (Google AI = pas de timeout Cloudflare)
MAX_DESC_LEN       = 200    # tronquer la description pour économiser les tokens
LLM_RETRY_MAX      = 3
LLM_SLEEP_BETWEEN  = 0.3    # secondes entre les appels LLM

# ── Validation ────────────────────────────────────────────────────────────────
if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌  NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY manquants dans .env.local")
    sys.exit(1)

if not GOOGLE_AI_API_KEY and not OPENAI_API_KEY and not OLLAMA_API_KEY:
    print("❌  Aucun LLM configuré. Définir GOOGLE_AI_API_KEY, OPENAI_API_KEY ou OLLAMA_CLOUD_API_KEY dans .env.local")
    sys.exit(1)

# Priorité : Google AI > OpenAI > Ollama
if GOOGLE_AI_API_KEY:
    LLM_BACKEND = "gemini"
elif OPENAI_API_KEY:
    LLM_BACKEND = "openai"
else:
    LLM_BACKEND = "ollama"


# ── Taxonomie ─────────────────────────────────────────────────────────────────
def _load_taxonomy() -> dict:
    if not TAXONOMY_PATH.exists():
        print(f"❌  Taxonomie introuvable : {TAXONOMY_PATH}")
        sys.exit(1)
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


TAXONOMY = _load_taxonomy()
VALID_PRODUCT_TYPES  = set(TAXONOMY["product_types"].keys())
VALID_ROOMS          = set(TAXONOMY["rooms"].keys())
VALID_USE_CATEGORIES = set(TAXONOMY["use_categories"].keys())
VALID_NICHES         = set(TAXONOMY["niches"].keys())


# ── Supabase helpers ──────────────────────────────────────────────────────────
def _sb_headers(extra: dict = None) -> dict:
    h = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
    }
    if extra:
        h.update(extra)
    return h


def sb_get(path: str, params: str = "") -> list:
    url = f"{SUPABASE_URL}/rest/v1/{path}{'?' + params if params else ''}"
    r = requests.get(url, headers=_sb_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def _patch_one(row: dict) -> bool:
    """PATCH un seul produit — thread-safe."""
    prod_id = row["id"]
    payload = {k: v for k, v in row.items() if k != "id"}
    try:
        r = requests.patch(
            f"{SUPABASE_URL}/rest/v1/products?id=eq.{prod_id}",
            headers=_sb_headers({"Prefer": "return=minimal"}),
            json=payload,
            timeout=15,
        )
        return r.status_code in (200, 204)
    except Exception:
        return False


def sb_patch_batch(rows: list[dict], dry_run: bool = False) -> int:
    """
    Met à jour les colonnes llm_* via PATCH individuel (parallèle).
    Evite les erreurs NOT NULL du POST upsert.
    Retourne le nombre de lignes effectivement écrites.
    """
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


# ── Prompt builder ────────────────────────────────────────────────────────────
def _build_system_prompt() -> str:
    pt_list  = ", ".join(VALID_PRODUCT_TYPES)
    rm_list  = ", ".join(VALID_ROOMS)
    uc_list  = ", ".join(VALID_USE_CATEGORIES)
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
- Si les infos sont insuffisantes pour classer, utilise les valeurs les plus génériques ("universel", "accessoire")

FORMAT DE RÉPONSE (JSON strict, AUCUN texte en dehors) :
{{"results": [{{"id": "ID_PRODUIT", "product_type": "clé", "room": "clé", "use_category": "clé", "niches": ["clé1", "clé2"]}}]}}"""


def _build_user_message(products: list[dict]) -> str:
    mini = []
    for p in products:
        desc = (p.get("description") or "")[:MAX_DESC_LEN]
        mini.append({
            "id":            str(p["id"]),
            "name":          p.get("name") or "",
            "brand":         p.get("brand") or "",
            "category_slug": p.get("category_slug") or "",
            "merchant_category": p.get("merchant_category") or "",
            "description":   desc,
        })
    return json.dumps(mini, ensure_ascii=False)


# ── LLM backends ──────────────────────────────────────────────────────────────
def _call_openai(system: str, user: str) -> Optional[str]:
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type":  "application/json",
        },
        json={
            "model":           "gpt-4o-mini",
            "messages":        [{"role": "system", "content": system},
                                {"role": "user",   "content": user}],
            "response_format": {"type": "json_object"},
            "temperature":     0,
            "max_tokens":      2048,
        },
        timeout=120,
    )
    if r.status_code != 200:
        print(f"    ⚠️  OpenAI HTTP {r.status_code}: {r.text[:200]}")
        return None
    data = r.json()
    return data["choices"][0]["message"]["content"]


def _call_ollama(system: str, user: str) -> Optional[str]:
    r = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        headers={
            "Authorization": f"Bearer {OLLAMA_API_KEY}",
            "Content-Type":  "application/json",
        },
        json={
            "model":    OLLAMA_MODEL,
            "messages": [{"role": "system", "content": system},
                         {"role": "user",   "content": user}],
            "stream":   False,
        },
        timeout=600,
    )
    if r.status_code != 200:
        print(f"    ⚠️  Ollama HTTP {r.status_code}: {r.text[:200]}")
        return None
    data = r.json()
    # Format Ollama Cloud
    if "message" in data:
        return data["message"].get("content", "")
    return data.get("response", "")


def _call_gemini(system: str, user: str) -> Optional[str]:
    """Appelle Google AI Gemini 2.0 Flash directement (sans Ollama Cloud, sans timeout Cloudflare)."""
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
        },
    }
    r = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    if r.status_code != 200:
        print(f"    ⚠️  Gemini HTTP {r.status_code}: {r.text[:300]}")
        return None
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        print(f"    ⚠️  Réponse Gemini inattendue: {e} — {str(data)[:200]}")
        return None


def _call_llm(system: str, user: str) -> Optional[str]:
    if LLM_BACKEND == "gemini":
        return _call_gemini(system, user)
    if LLM_BACKEND == "openai":
        return _call_openai(system, user)
    return _call_ollama(system, user)


# ── Response parser ───────────────────────────────────────────────────────────
def _parse_response(raw: str, products: list[dict]) -> list[dict]:
    """
    Parse la réponse JSON du LLM.
    Valide chaque valeur contre la taxonomie ; remplace les valeurs invalides
    par des défauts sûrs plutôt que de planter.
    """
    product_ids = {str(p["id"]) for p in products}
    results = []

    try:
        # Extraire le JSON même si le LLM ajoute du texte autour
        raw = raw.strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("Pas de JSON trouvé dans la réponse")
        data = json.loads(raw[start:end])
        items = data.get("results", [])
    except (json.JSONDecodeError, ValueError) as e:
        print(f"    ⚠️  Parse JSON échoué: {e} — raw[:200]: {raw[:200]}")
        return []

    for item in items:
        pid = str(item.get("id", ""))
        if pid not in product_ids:
            continue  # hallucination d'ID

        pt  = item.get("product_type", "autre")
        rm  = item.get("room", "universel")
        uc  = item.get("use_category", "accessoire")
        ni  = item.get("niches", [])

        # Validation et correction silencieuse
        if pt not in VALID_PRODUCT_TYPES:
            pt = "autre"
        if rm not in VALID_ROOMS:
            rm = "universel"
        if uc not in VALID_USE_CATEGORIES:
            uc = "accessoire"
        if not isinstance(ni, list):
            ni = []
        ni = [n for n in ni if n in VALID_NICHES][:4]  # max 4, valides seulement

        results.append({
            "id":                pid,
            "product_type":      pt,
            "room":              rm,
            "use_category":      uc,
            "niches":            ni,
        })

    return results


# ── Batch classification ─────────────────────────────────────────────────────
def classify_batch(products: list[dict], system: str) -> list[dict]:
    """Classifie un batch de produits avec retry. Retourne les classifications."""
    user_msg = _build_user_message(products)

    for attempt in range(1, LLM_RETRY_MAX + 1):
        raw = _call_llm(system, user_msg)
        if raw is None:
            if attempt < LLM_RETRY_MAX:
                time.sleep(2 ** attempt)
            continue
        parsed = _parse_response(raw, products)
        if len(parsed) >= len(products) * 0.5:  # au moins 50% de réponses valides
            return parsed
        print(f"    ↺  Tentative {attempt}/{LLM_RETRY_MAX} — seulement {len(parsed)}/{len(products)} résultats valides")
        if attempt < LLM_RETRY_MAX:
            time.sleep(2)

    print(f"  ⚠️  Batch échoué après {LLM_RETRY_MAX} tentatives — produits ignorés")
    return []


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Classifie les produits Supabase via LLM")
    parser.add_argument("--force",       action="store_true",
                        help="Re-classifier même les produits déjà classifiés")
    parser.add_argument("--merchant",    type=str, default=None,
                        help="Limiter à un seul merchant_key (ex: imou_fr)")
    parser.add_argument("--limit",       type=int, default=None,
                        help="Nombre maximum de produits à traiter")
    parser.add_argument("--batch-size",  type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"Produits par appel LLM (défaut: {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--dry-run",     action="store_true",
                        help="Affiche les classifications sans écrire en DB")
    args = parser.parse_args()

    _model_label = (
        f"{GOOGLE_AI_MODEL} (Google AI)" if LLM_BACKEND == "gemini"
        else "gpt-4o-mini" if LLM_BACKEND == "openai"
        else OLLAMA_MODEL
    )
    print(f"""
══════════════════════════════════════════════════════════
  🤖  Classify Products — LLM Taxonomy
  Backend : {LLM_BACKEND.upper()} ({_model_label})
  Batch   : {args.batch_size} produits / appel
  Force   : {'oui' if args.force else 'non (skip déjà classifiés)'}
  {"Mode DRY-RUN (pas d'ecriture DB)" if args.dry_run else "Mode PRODUCTION (ecriture DB)"}
══════════════════════════════════════════════════════════
""")

    system_prompt = _build_system_prompt()

    # ── Récupérer les produits à classifier ──────────────────────────────────
    all_products: list[dict] = []
    offset = 0

    base_filter = "active=not.is.false"
    if not args.force:
        base_filter += "&llm_classified_at=is.null"
    if args.merchant:
        base_filter += f"&merchant_key=eq.{args.merchant}"

    print("🔍  Récupération des produits depuis Supabase…")
    while True:
        params = (
            f"{base_filter}"
            "&select=id,name,brand,category_slug,merchant_category,description"
            f"&order=id.asc&limit={PAGE_SIZE}&offset={offset}"
        )
        try:
            page = sb_get("products", params)
        except Exception as e:
            print(f"❌  Supabase fetch: {e}")
            sys.exit(1)

        if not page:
            break
        all_products.extend(page)
        offset += len(page)
        print(f"  → {len(all_products)} produits récupérés…", end="\r")

        if args.limit and len(all_products) >= args.limit:
            all_products = all_products[:args.limit]
            break
        if len(page) < PAGE_SIZE:
            break

    print(f"\n  ✅  {len(all_products)} produits à classifier")

    if not all_products:
        print("  ℹ️  Aucun produit à classifier — arrêt")
        return

    # ── Découper en batches et classifier ────────────────────────────────────
    total_classified = 0
    total_written    = 0
    n_batches = (len(all_products) + args.batch_size - 1) // args.batch_size

    for batch_idx in range(n_batches):
        start = batch_idx * args.batch_size
        end   = start + args.batch_size
        batch = all_products[start:end]

        print(f"\n  📦  Batch {batch_idx + 1}/{n_batches} ({len(batch)} produits)…")

        classifications = classify_batch(batch, system_prompt)
        if not classifications:
            continue

        # Préparer les rows pour l'upsert
        now_iso = datetime.now(timezone.utc).isoformat()
        upsert_rows = []
        for c in classifications:
            upsert_rows.append({
                "id":                 c["id"],
                "llm_product_type":   c["product_type"],
                "llm_room":           c["room"],
                "llm_use_category":   c["use_category"],
                "llm_niches":         c["niches"],
                "llm_classified_at":  now_iso,
            })

        # Affichage dry-run
        if args.dry_run:
            for r in upsert_rows[:3]:
                print(f"     [DRY] {r['id'][:8]}… → {r['llm_product_type']} | {r['llm_room']} | {r['llm_use_category']} | {r['llm_niches']}")
            if len(upsert_rows) > 3:
                print(f"     … et {len(upsert_rows)-3} autres")
        else:
            for r in upsert_rows[:2]:
                pid_short = str(r['id'])[:8]
                print(f"     ✓ {pid_short}… → {r['llm_product_type']} | niches: {r['llm_niches']}")

        written = sb_patch_batch(upsert_rows, dry_run=args.dry_run)
        total_classified += len(classifications)
        total_written    += written

        if not args.dry_run:
            time.sleep(LLM_SLEEP_BETWEEN)

    # ── Résumé final ─────────────────────────────────────────────────────────
    print(f"""
══════════════════════════════════════════════════════════
  ✅  Classification terminée
  Produits classifiés : {total_classified} / {len(all_products)}
  Lignes écrites DB   : {total_written if not args.dry_run else 'N/A (dry-run)'}
══════════════════════════════════════════════════════════

Prochaine étape : tester la génération d'articles :
  python3 scripts/generate-lifestyle-article.py --dry-run --no-images --niche gaming_setup
""")


if __name__ == "__main__":
    main()
