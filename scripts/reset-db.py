#!/usr/bin/env python3
"""
reset-db.py — Vide TOUTES les tables Supabase de MyGoodPick.
Usage:
  python3 scripts/reset-db.py          # demande confirmation
  python3 scripts/reset-db.py --yes    # sans prompt (CI / automation)
"""
import os, sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env.local")
except ImportError:
    pass

try:
    from supabase import create_client
except ImportError:
    print("❌  pip install supabase")
    sys.exit(1)

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌  SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis dans .env.local")
    sys.exit(1)

yes = "--yes" in sys.argv
if not yes:
    ans = input("⚠  Cette action supprime TOUTES les données. Écrire 'RESET' pour confirmer : ")
    if ans.strip() != "RESET":
        print("Annulé.")
        sys.exit(0)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Ordre important : respecter les FK (supprimer les enfants avant les parents)
TABLES = [
    "affiliate_links",
    "comparison_products",
    "pinterest_pins",
    "comparisons",
    "products",
    "categories",
]

print("\n🗑   Suppression en cours…")
for table in TABLES:
    sb.table(table).delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    print(f"  ✅  {table} vidée")

print("\n✅  Base complètement vidée.")
print("   Lance ensuite : python3 scripts/seed-comparatifs.py")
