#!/usr/bin/env python3
"""
check_links.py — Validation des liens produits
===============================================

Vérifie que les URLs directes des produits (product_url) sont accessibles.
Marque active=false les produits dont le lien :
  - Retourne un HTTP 4xx (produit introuvable)
  - Redirige vers la page d'accueil du marchand (URL racine)
  - Échoue à répondre (timeout, connexion refusée)

Les liens brisés sont déjà cachés sur le site (active=false dans Supabase).

Usage :
    python3 check_links.py                   # vérifie tous les produits actifs
    python3 check_links.py --merchant fnac   # un seul marchand
    python3 check_links.py --dry-run         # affiche sans écrire en base
    python3 check_links.py --workers 30      # plus de parallélisme
    python3 check_links.py --limit 1000      # tranche limitée
"""

import argparse
import concurrent.futures
import json
import sys
import time
from urllib.parse import urlparse

import requests

from settings import SUPABASE_URL, SUPABASE_KEY, sb_headers, check_supabase

# ── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_WORKERS  = 20
DEFAULT_TIMEOUT  = 10      # secondes par requête
PAGE_SIZE        = 1000    # produits par page Supabase

# Headers simulant un navigateur pour éviter les blocages simples
CHECK_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LinkChecker/1.0)",
    "Accept": "text/html,application/xhtml+xml,*/*",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_homepage_redirect(original_url: str, final_url: str) -> bool:
    """Vrai si la redirection atterrit sur la page d'accueil du domaine."""
    try:
        orig  = urlparse(original_url)
        final = urlparse(final_url)
        if orig.netloc != final.netloc:
            return False
        # Page d'accueil : chemin vide ou "/" (avec ou sans query)
        path = final.path.rstrip("/")
        return path == "" or path in ("/fr", "/en", "/home")
    except Exception:
        return False


def _check_url(product: dict) -> dict:
    """
    Vérifie product_url avec HEAD (fallback GET si 405).
    Retourne {"id": ..., "status": "ok"|"broken"|"skip", "reason": "..."}
    """
    pid  = product["id"]
    url  = (product.get("product_url") or "").strip()

    if not url:
        return {"id": pid, "status": "skip", "reason": "no_url"}

    try:
        resp = requests.head(
            url, allow_redirects=True,
            timeout=DEFAULT_TIMEOUT, headers=CHECK_HEADERS,
        )
        # Certains serveurs refusent HEAD → GET
        if resp.status_code == 405:
            resp = requests.get(
                url, allow_redirects=True,
                timeout=DEFAULT_TIMEOUT, headers=CHECK_HEADERS,
                stream=True,
            )
            resp.close()

        final_url = resp.url
        code      = resp.status_code

        if code == 429:
            return {"id": pid, "status": "skip", "reason": "rate_limited"}

        if code >= 400:
            return {"id": pid, "status": "broken", "reason": f"http_{code}", "url": url}

        if _is_homepage_redirect(url, final_url):
            return {"id": pid, "status": "broken", "reason": "homepage_redirect",
                    "url": url, "final": final_url}

        return {"id": pid, "status": "ok", "reason": f"http_{code}"}

    except requests.exceptions.Timeout:
        return {"id": pid, "status": "skip", "reason": "timeout"}
    except requests.exceptions.ConnectionError:
        return {"id": pid, "status": "skip", "reason": "connection_error"}
    except Exception as e:
        return {"id": pid, "status": "broken", "reason": f"error: {e}", "url": url}


# ── Supabase ──────────────────────────────────────────────────────────────────

def _fetch_products(merchant: str | None, limit: int | None) -> list[dict]:
    """Récupère tous les produits actifs avec product_url renseignée."""
    products = []
    offset   = 0
    base     = "active=not.is.false&product_url=not.is.null"
    if merchant:
        base += f"&merchant_key=eq.{merchant}"

    print("🔍  Récupération des produits…")
    while True:
        params = (
            f"{base}&select=id,name,product_url,merchant_key"
            f"&order=id.asc&limit={PAGE_SIZE}&offset={offset}"
        )
        try:
            r = requests.get(
                f"{SUPABASE_URL}/rest/v1/products?{params}",
                headers=sb_headers(), timeout=30,
            )
            r.raise_for_status()
            page = r.json()
        except Exception as e:
            print(f"  ⚠  Erreur fetch page {offset}: {e}")
            break

        if not page:
            break
        products.extend(page)
        offset += len(page)
        if limit and len(products) >= limit:
            products = products[:limit]
            break
        if len(page) < PAGE_SIZE:
            break

    print(f"  ✅  {len(products)} produits à vérifier\n")
    return products


def _mark_inactive_batch(ids: list[str], dry_run: bool) -> int:
    """Marque active=false une liste de product IDs."""
    if not ids:
        return 0
    if dry_run:
        print(f"  [DRY] Marquerait {len(ids)} produits comme inactifs")
        return len(ids)

    chunk_size = 200
    total = 0
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i:i + chunk_size]
        ids_param = ",".join(f'"{pid}"' for pid in chunk)
        try:
            r = requests.patch(
                f"{SUPABASE_URL}/rest/v1/products?id=in.({ids_param})",
                headers=sb_headers({"Prefer": "return=minimal"}),
                json={"active": False},
                timeout=30,
            )
            r.raise_for_status()
            total += len(chunk)
        except Exception as e:
            print(f"  ⚠  Erreur PATCH batch {i}: {e}")
    return total


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Valide les liens produits et désactive les liens brisés",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--merchant", default=None, metavar="KEY",
                        help="Filtrer par marchand")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"Nombre de workers parallèles (défaut: {DEFAULT_WORKERS})")
    parser.add_argument("--limit", type=int, default=None,
                        help="Nombre max de produits à vérifier")
    parser.add_argument("--dry-run", action="store_true",
                        help="Afficher les résultats sans écrire en base")
    parser.add_argument("--output", default=None, metavar="FILE",
                        help="Sauvegarder le rapport JSON dans un fichier")
    args = parser.parse_args()

    print(f"\n{'═'*62}")
    print(f"  🔗  check_links.py — Validation des liens produits")
    if args.merchant:
        print(f"  Marchand : {args.merchant}")
    if args.dry_run:
        print("  Mode DRY-RUN")
    print(f"  Workers  : {args.workers}")
    print(f"{'═'*62}\n")

    check_supabase()
    products = _fetch_products(args.merchant, args.limit)
    if not products:
        print("  ℹ️  Aucun produit à vérifier")
        return

    # ── Vérification parallèle ────────────────────────────────────────────────
    broken  = []
    ok      = 0
    skipped = 0
    errors  = []
    done    = 0
    total   = len(products)
    t_start = time.time()

    print(f"▶  {total} produits · {args.workers} workers\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_check_url, p): p for p in products}
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            done += 1

            if res["status"] == "ok":
                ok += 1
            elif res["status"] == "broken":
                broken.append(res)
                reason = res["reason"]
                url    = res.get("url", "")[:80]
                name   = futures[fut].get("name", "")[:50]
                print(f"  ❌  [{reason}]  {name}  — {url}")
            else:
                skipped += 1

            # Progress toutes les 100 vérifications
            if done % 100 == 0 or done == total:
                elapsed = time.time() - t_start
                speed   = done / elapsed if elapsed > 0 else 0
                print(f"  … {done}/{total}  "
                      f"ok={ok}  brisés={len(broken)}  "
                      f"({speed:.0f} req/s)")

    # ── Rapport ───────────────────────────────────────────────────────────────
    elapsed = time.time() - t_start
    print(f"\n{'═'*62}")
    print(f"  Vérifiés  : {total}")
    print(f"  OK        : {ok}")
    print(f"  Brisés    : {len(broken)}")
    print(f"  Sans URL  : {skipped}")
    print(f"  Durée     : {elapsed:.0f}s")
    print(f"{'═'*62}\n")

    if args.output:
        import pathlib
        pathlib.Path(args.output).write_text(
            json.dumps(broken, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  📄  Rapport sauvegardé : {args.output}")

    # ── Désactivation DB ──────────────────────────────────────────────────────
    if broken:
        broken_ids = [r["id"] for r in broken]

        # Répartition par raison
        by_reason: dict[str, int] = {}
        for r in broken:
            by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
        for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
            print(f"    {count:>5}  {reason}")
        print()

        disabled = _mark_inactive_batch(broken_ids, args.dry_run)
        action = "[DRY]" if args.dry_run else "✅ "
        print(f"  {action}  {disabled} produits marqués inactive=false")


if __name__ == "__main__":
    main()
