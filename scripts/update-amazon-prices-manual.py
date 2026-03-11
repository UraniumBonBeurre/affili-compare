#!/usr/bin/env python3
"""
update-amazon-prices-manual.py — Interface CLI pour mettre à jour les prix Amazon manuellement.

À lancer 1 fois par semaine jusqu'à l'activation de la PA-API.
Affiche chaque produit Amazon dans Supabase, demande le prix actuel,
met à jour la base de données.

# TODO: remplacer par PA-API dès que paapi_enabled = true
# Voir : https://webservices.amazon.fr/paapi5/documentation/

Usage :
  SUPABASE_URL=https://xxx.supabase.co \
  SUPABASE_SERVICE_ROLE_KEY=eyJ... \
  python scripts/update-amazon-prices-manual.py

Options :
  --auto-check    Vérifie uniquement les prix qui n'ont pas été mis à jour depuis 7 jours
  --product SLUG  Met à jour un seul produit par son nom (partiel)
"""

import argparse
import os
import sys
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env.local"))
except ImportError:
    pass

try:
    from supabase import create_client
except ImportError:
    print("pip install supabase python-dotenv")
    sys.exit(1)

SUPABASE_URL = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
AMAZON_TAG   = os.environ.get("AMAZON_ASSOCIATE_TAG_FR", "monsite-21")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌  Variables manquantes : SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Couleurs terminal ──────────────────────────────────────────

BOLD    = "\033[1m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
CYAN    = "\033[96m"
RESET   = "\033[0m"
DIM     = "\033[2m"


def header():
    print(f"\n{BOLD}{'═'*58}{RESET}")
    print(f"{BOLD}  AffiliCompare — Mise à jour des prix Amazon FR{RESET}")
    print(f"{DIM}  # TODO: remplacer par PA-API dès que paapi_enabled = true{RESET}")
    print(f"{BOLD}{'═'*58}{RESET}\n")


def load_amazon_links(product_filter: str | None, stale_only: bool) -> list[dict]:
    """Charge les liens Amazon depuis Supabase."""
    query = (
        sb.table("affiliate_links")
        .select("id, product_id, url, price, currency, in_stock, last_checked, paapi_enabled, products(name, brand)")
        .eq("partner", "amazon_fr")
        .eq("paapi_enabled", False)  # uniquement les liens sans PA-API
    )

    if stale_only:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        query  = query.lt("last_checked", cutoff)

    res = query.execute()
    links = res.data or []

    if product_filter:
        term   = product_filter.lower()
        links  = [l for l in links if term in (l["products"]["name"] or "").lower()]

    return links


def format_age(last_checked_iso: str) -> str:
    """Affiche l'âge de la dernière vérification de façon lisible."""
    try:
        last = datetime.fromisoformat(last_checked_iso.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - last
        days  = delta.days
        if days == 0:
            return f"{GREEN}Aujourd'hui{RESET}"
        elif days <= 3:
            return f"{YELLOW}{days}j{RESET}"
        else:
            return f"{RED}{days}j — À mettre à jour !{RESET}"
    except Exception:
        return "??"


def update_price(link_id: str, price: float, in_stock: bool) -> None:
    """Met à jour le prix et le stock dans Supabase."""
    sb.table("affiliate_links").update({
        "price":        price,
        "in_stock":     in_stock,
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }).eq("id", link_id).execute()


def run(product_filter: str | None, stale_only: bool) -> None:
    header()
    links = load_amazon_links(product_filter, stale_only)

    if not links:
        if stale_only:
            print(f"{GREEN}✅  Tous les prix sont à jour (< 7 jours).{RESET}")
        else:
            print(f"{YELLOW}⚠️  Aucun lien Amazon trouvé sans PA-API.{RESET}")
        return

    print(f"  {len(links)} produit(s) à vérifier\n")
    print(f"  {'Produit':<35} {'Prix actuel':>12}  {'Âge'}")
    print(f"  {'-'*35} {'-'*12}  {'-'*20}")

    for link in links:
        product_name = link["products"]["name"]
        brand        = link["products"]["brand"]
        price_str    = f"{link['price']:.2f} €" if link["price"] else "—"
        age_str      = format_age(link["last_checked"])
        print(f"  {brand} {product_name[:32]:<32} {price_str:>12}  {age_str}")

    print()

    updated = skipped = 0

    for i, link in enumerate(links, 1):
        product_name = link["products"]["name"]
        brand        = link["products"]["brand"]
        current_price = link["price"]
        amazon_url    = link["url"]

        print(f"\n{'─'*58}")
        print(f"{BOLD}[{i}/{len(links)}] {brand} – {product_name}{RESET}")
        print(f"  URL Amazon : {CYAN}{amazon_url}{RESET}")
        print(f"  Prix actuel en base : {BOLD}{current_price} €{RESET}")
        print()
        print(f"  Ouvrir l'URL ci-dessus, vérifier le prix et saisir ci-dessous.")
        print(f"  {DIM}(Appuyez sur Entrée sans valeur pour garder le prix actuel | 's' pour passer){RESET}")

        # Prix
        while True:
            raw = input(f"  Nouveau prix (€) : ").strip()
            if raw.lower() == "s":
                print(f"  {YELLOW}→ Ignoré{RESET}")
                skipped += 1
                break
            if raw == "":
                new_price = current_price
                print(f"  → Prix conservé : {new_price} €")
            else:
                raw = raw.replace(",", ".")
                try:
                    new_price = float(raw)
                except ValueError:
                    print(f"  {RED}Valeur invalide, réessayez.{RESET}")
                    continue

            # Stock
            while True:
                stock_raw = input(f"  En stock ? [O/n] : ").strip().lower()
                if stock_raw in ("", "o", "oui", "y", "yes"):
                    in_stock = True
                    break
                elif stock_raw in ("n", "non", "no"):
                    in_stock = False
                    break
                else:
                    print(f"  {RED}Répondre O ou n{RESET}")

            update_price(link["id"], new_price, in_stock)
            stock_label = f"{GREEN}En stock{RESET}" if in_stock else f"{RED}Rupture{RESET}"
            print(f"  {GREEN}✅  Sauvegardé : {new_price} € — {stock_label}{RESET}")
            updated += 1
            break

    print(f"\n{'═'*58}")
    print(f"{BOLD}  Terminé : {updated} prix mis à jour, {skipped} ignorés.{RESET}")

    if updated > 0:
        print(f"\n  {DIM}Les pages ISR seront revalidées automatiquement lors du prochain build{RESET}")
        print(f"  {DIM}ou déclenchez manuellement : python scripts/revalidate-isr.py{RESET}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mise à jour manuelle des prix Amazon")
    parser.add_argument("--auto-check", action="store_true", help="Uniquement les prix > 7 jours")
    parser.add_argument("--product",    type=str,            help="Filtrer par nom de produit")
    args = parser.parse_args()

    run(product_filter=args.product, stale_only=args.auto_check)
