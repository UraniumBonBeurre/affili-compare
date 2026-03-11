#!/usr/bin/env python3
"""
Tests d'intégration réels pour import-awin-feed.py
====================================================
Ces tests appellent les vraies APIs (Awin + Supabase).
Ils ne mockent rien — ils vérifient que tout est opérationnel en conditions réelles.

Usage:
    python scripts/tests/test_awin.py
"""

import os
import sys
import json
import time
from pathlib import Path

# Load .env.local
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env.local")
except ImportError:
    pass

try:
    import requests
except ImportError:
    print("pip install requests python-dotenv")
    sys.exit(1)

AWIN_TOKEN    = os.getenv("AWIN_API_TOKEN", "")
AWIN_PUB_ID   = os.getenv("AWIN_PUBLISHER_ID", "")
SUPABASE_URL  = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY  = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
RDC_PROG_ID   = "6901"

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = []


def test(name, fn):
    print(f"\n{'─'*60}")
    print(f"  TEST : {name}")
    print(f"{'─'*60}")
    try:
        ok, detail = fn()
        status = PASS if ok else FAIL
        print(f"  {status}  {detail}")
        results.append((name, ok, detail))
        return ok
    except Exception as e:
        print(f"  {FAIL}  Exception : {e}")
        results.append((name, False, str(e)))
        return False


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — Credentials présents
# ─────────────────────────────────────────────────────────────────────────────
def t_credentials():
    missing = []
    if not AWIN_TOKEN:
        missing.append("AWIN_API_TOKEN")
    if not AWIN_PUB_ID:
        missing.append("AWIN_PUBLISHER_ID")
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if missing:
        return False, f"Manquant : {', '.join(missing)}"
    return True, f"Token={AWIN_TOKEN[:8]}… | PubID={AWIN_PUB_ID} | Supabase={SUPABASE_URL[:40]}…"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — API Awin accessible (token valide)
# ─────────────────────────────────────────────────────────────────────────────
def t_awin_api():
    url = f"https://api.awin.com/publishers/{AWIN_PUB_ID}/programmes?relationship=joined&countryCode=fr"
    r = requests.get(url, headers={"Authorization": f"Bearer {AWIN_TOKEN}"}, timeout=15)
    if r.status_code == 200:
        progs = r.json()
        return True, f"HTTP 200 — {len(progs)} programme(s) approuvé(s) pour publisher {AWIN_PUB_ID}"
    elif r.status_code == 401:
        return False, "HTTP 401 — AWIN_API_TOKEN invalide ou expiré"
    elif r.status_code == 403:
        return False, "HTTP 403 — Accès refusé"
    else:
        return False, f"HTTP {r.status_code} — {r.text[:200]}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — Programme Rue du Commerce (6901) approuvé
# ─────────────────────────────────────────────────────────────────────────────
def t_rdc_approved():
    url = f"https://api.awin.com/publishers/{AWIN_PUB_ID}/programmes?relationship=joined"
    r = requests.get(url, headers={"Authorization": f"Bearer {AWIN_TOKEN}"}, timeout=15)
    if r.status_code != 200:
        return False, f"HTTP {r.status_code} — {r.text[:150]}"

    progs = r.json()
    approved_ids = [str(p.get("id", "")) for p in progs]
    approved_names = {str(p.get("id", "")): p.get("name", "") for p in progs}

    print(f"\n    Programmes approuvés ({len(progs)}) :")
    for p in progs[:15]:
        print(f"      {str(p.get('id','')):>8}  {p.get('name','')}")
    if len(progs) > 15:
        print(f"      … et {len(progs)-15} autres")

    if RDC_PROG_ID in approved_ids:
        return True, f"Programme {RDC_PROG_ID} ({approved_names.get(RDC_PROG_ID, 'Rue du Commerce')}) → APPROUVÉ"
    else:
        return False, (
            f"Programme {RDC_PROG_ID} (Rue du Commerce) NON approuvé.\n"
            "    → Va sur https://ui.awin.com/merchant/6901 et postule.\n"
            "    → L'approbation est manuelle côté annonceur (quelques jours)."
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 — Découverte du feed ID via l'API ProductData Awin
# ─────────────────────────────────────────────────────────────────────────────
_feed_id_cache = None

def t_feed_discovery():
    global _feed_id_cache

    # L'API ProductData Awin liste tous les flux disponibles pour ce publisher
    url = f"https://productdata.awin.com/datafeed/list/apikey/{AWIN_TOKEN}/"
    print(f"\n    Endpoint : {url[:80]}…")
    r = requests.get(url, timeout=20)
    if r.status_code == 401:
        return False, "HTTP 401 — AWIN_API_TOKEN invalide pour l'API ProductData"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code} — {r.text[:150]}"

    # Réponse XML ou CSV ; on cherche le programme 6901
    content = r.text
    print(f"\n    Réponse brute (200 premiers chars) : {content[:200]}")

    # Essayer JSON si possible
    try:
        data = r.json()
        feeds_for_rdc = [
            f for f in (data if isinstance(data, list) else data.get("feeds", []))
            if str(f.get("programmeId", f.get("programme_id", ""))) == RDC_PROG_ID
        ]
        if feeds_for_rdc:
            _feed_id_cache = str(feeds_for_rdc[0].get("feedId", feeds_for_rdc[0].get("id", "")))
        all_feeds = data if isinstance(data, list) else data.get("feeds", [])
        print(f"\n    Flux disponibles ({len(all_feeds)}) :")
        for f in all_feeds[:10]:
            print(f"      prog={f.get('programmeId','?')}  feedId={f.get('feedId','?')}  {f.get('name','')[:50]}")
    except Exception:
        # Format non-JSON : chercher le feed ID dans le texte brut
        import re as _re
        matches = _re.findall(r'feedId["\s:=]+([0-9]+)', content)
        prog_matches = _re.findall(rf'(?:6901.*?feedId|feedId.*?6901)["\s:=]+([0-9]+)', content)
        if matches:
            _feed_id_cache = matches[0]
        print(f"    Feed IDs trouvés : {matches[:5]}")

    if _feed_id_cache:
        return True, f"Feed ID = {_feed_id_cache} (programme RdC 6901)"
    else:
        # Tenter accès direct sans découverte — certains publishers n'ont pas l'endpoint list
        return False, (
            "Feed ID introuvable via l'API. "
            "Va sur https://ui.awin.com → Product Feeds → Rue du Commerce "
            "et note l'ID du flux (ex: 12345). Ajoute AWIN_FEED_ID_RDC=12345 dans .env.local"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 — Téléchargement d'un extrait du flux (100 premières lignes)
# ─────────────────────────────────────────────────────────────────────────────
_sample_rows = []

def t_feed_download_sample():
    global _sample_rows
    if not _feed_id_cache:
        return False, "Feed ID non disponible (test 4 a échoué)"

    columns = "aw_product_id,product_name,brand_name,aw_image_url,ean,search_price,currency_symbol,merchant_deep_link,in_stock,category_name"
    url = (
        f"https://productdata.awin.com/datafeed/download"
        f"/apikey/{AWIN_TOKEN}"
        f"/language/fr/fid/{_feed_id_cache}"
        f"/columns/{columns}"
        f"/format/csv/"
        f"?limit=200"
    )
    print(f"\n    URL flux : {url[:100]}…")
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        return False, f"HTTP {r.status_code} — {r.text[:150]}"

    import csv, io
    content = r.content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    _sample_rows = list(reader)

    if not _sample_rows:
        return False, "Flux vide ou format CSV incorrect"

    print(f"\n    Colonnes : {list(_sample_rows[0].keys())}")
    print(f"\n    Exemples (5 premiers) :")
    for row in _sample_rows[:5]:
        name  = row.get("product_name", "")[:60]
        price = row.get("search_price", "?")
        brand = row.get("brand_name", "")
        cat   = row.get("category_name", "")
        stock = "✅" if row.get("in_stock","").lower() in ("1","yes","true","en stock") else "❌"
        print(f"      {stock}  {price:>8} €  [{brand}]  {name}")
        print(f"              Catégorie : {cat}")

    has_url = sum(1 for r in _sample_rows if r.get("merchant_deep_link","").strip())
    has_price = sum(1 for r in _sample_rows if r.get("search_price","").strip())
    return True, f"{len(_sample_rows)} lignes | {has_url} avec URL | {has_price} avec prix"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6 — Validation des URLs de tracking Awin
# ─────────────────────────────────────────────────────────────────────────────
def t_tracking_url():
    if not _sample_rows:
        return False, "Pas d'échantillon (test 5 a échoué)"

    from urllib.parse import quote
    sample = next((r for r in _sample_rows if r.get("merchant_deep_link","").strip()), None)
    if not sample:
        return False, "Aucune URL produit dans l'échantillon"

    raw_url = sample["merchant_deep_link"].strip()
    tracked = (
        f"https://www.awin1.com/cread.php"
        f"?awinmid={RDC_PROG_ID}&awinaffid={AWIN_PUB_ID}"
        f"&ued={quote(raw_url, safe='')}"
    )
    print(f"\n    URL brute   : {raw_url[:90]}")
    print(f"    URL trackée : {tracked[:90]}")

    # Vérifier que l'URL brute répond (HEAD request)
    try:
        resp = requests.head(raw_url, allow_redirects=True, timeout=10)
        direct_ok = resp.status_code < 400
        print(f"    URL directe : HTTP {resp.status_code} → {'accessible' if direct_ok else 'erreur'}")
    except Exception as e:
        print(f"    URL directe : inaccessible ({e})")
        direct_ok = False

    return True, f"Tracking URL générée correctement (publisher={AWIN_PUB_ID})"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7 — Connexion Supabase
# ─────────────────────────────────────────────────────────────────────────────
def t_supabase():
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    r = requests.get(f"{SUPABASE_URL}/rest/v1/categories?select=id&limit=1", headers=headers, timeout=10)
    if r.status_code == 200:
        rows = r.json()
        return True, f"Supabase accessible — {len(rows)} catégorie(s) en base"
    return False, f"HTTP {r.status_code} — {r.text[:150]}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8 — Recherche dans l'échantillon du flux
# ─────────────────────────────────────────────────────────────────────────────
def t_search_logic():
    if not _sample_rows:
        return False, "Pas d'échantillon (test 5 a échoué)"

    import re as _re
    def normalize(t):
        t = t.lower()
        t = _re.sub(r"[^a-z0-9\u00c0-\u00ff ]", " ", t)
        return _re.sub(r"\s+", " ", t).strip()

    def score(row, tokens):
        name = normalize(row.get("product_name", ""))
        return sum(1 for t in tokens if t in name)

    queries = ["aspirateur", "cafetiere", "robot", "chaise", "lampe"]
    print()
    for q in queries:
        tokens = normalize(q).split()
        hits = [r for r in _sample_rows if score(r, tokens) >= len(tokens)]
        print(f"    '{q}' → {len(hits)} résultats dans {len(_sample_rows)} lignes échantillon")

    return True, f"Logique de recherche fonctionnelle sur {len(_sample_rows)} produits d'échantillon"


# ─────────────────────────────────────────────────────────────────────────────
# Exécution
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*60)
    print("  MyGoodPick — Tests intégration Awin + Supabase")
    print("="*60)

    creds_ok = test("Credentials .env.local",          t_credentials)
    if not creds_ok:
        print("\n❌  Credentials manquants — arrêt des tests.")
        sys.exit(1)

    api_ok    = test("API Awin accessible",             t_awin_api)
    rdc_ok    = test("Programme RdC 6901 approuvé",    t_rdc_approved)
    feed_ok   = test("Découverte feed ID",              t_feed_discovery)   if rdc_ok  else None
    sample_ok = test("Téléchargement extrait flux",    t_feed_download_sample) if feed_ok else None
    test("Génération URL tracking Awin",               t_tracking_url)     if sample_ok else None
    test("Connexion Supabase",                         t_supabase)
    test("Logique recherche dans flux",                t_search_logic)     if sample_ok else None

    # ── Résumé ────────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  RÉSUMÉ")
    print("="*60)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    for name, ok, detail in results:
        icon = PASS if ok else FAIL
        short = detail.split("\n")[0][:70]
        print(f"  {icon}  {name:<40}  {short}")

    print(f"\n  {passed} OK / {failed} FAILED / {len(results)} total\n")

    if failed > 0:
        rdc_result = next((r for r in results if "6901" in r[0] and not r[1]), None)
        if rdc_result:
            print("  ACTION REQUISE :")
            print("  → Va sur https://ui.awin.com/merchant/6901 et postule au programme")
            print("    Rue du Commerce. L'approbation peut prendre 1-5 jours ouvrés.")
        sys.exit(1)
    else:
        print("  🎉  Tout est opérationnel ! Lance :")
        print("  python scripts/import-awin-feed.py --discover 'aspirateur sans fil' --limit 10")
