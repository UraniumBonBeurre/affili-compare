#!/usr/bin/env python3
"""
seed-categories.py — Insère les 8 catégories du site dans Supabase.
Usage: python3 scripts/seed-categories.py
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
    print("❌  SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

CATEGORIES = [
    {"slug": "informatique",  "name_fr": "Informatique",     "name_en": "Computers",   "name_de": "Computer",       "icon": "💻", "meta_description_fr": "PC portables, SSD, claviers, écrans…",         "is_active": True, "display_order": 1},
    {"slug": "gaming",        "name_fr": "Gaming",           "name_en": "Gaming",      "name_de": "Gaming",         "icon": "🎮", "meta_description_fr": "Fauteuils, casques, souris, tapis de jeu…",    "is_active": True, "display_order": 2},
    {"slug": "tv-hifi",       "name_fr": "TV & Hi-Fi",       "name_en": "TV & Hi-Fi",  "name_de": "TV & HiFi",      "icon": "📺", "meta_description_fr": "Téléviseurs, enceintes, barres de son…",       "is_active": True, "display_order": 3},
    {"slug": "smartphone",    "name_fr": "Smartphone",       "name_en": "Smartphone",  "name_de": "Smartphone",     "icon": "📱", "meta_description_fr": "Smartphones Android, iPhone, tablettes…",      "is_active": True, "display_order": 4},
    {"slug": "electromenager","name_fr": "Électroménager",   "name_en": "Appliances",  "name_de": "Haushaltsgeräte","icon": "🔌", "meta_description_fr": "Lave-linge, réfrigérateurs, aspirateurs…",    "is_active": True, "display_order": 5},
    {"slug": "cuisine",       "name_fr": "Cuisine",          "name_en": "Kitchen",     "name_de": "Küche",          "icon": "🍳", "meta_description_fr": "Robots ménagers, cafetières, micro-ondes…",    "is_active": True, "display_order": 6},
    {"slug": "maison",        "name_fr": "Maison & Déco",    "name_en": "Home & Decor","name_de": "Haus & Deko",    "icon": "🏠", "meta_description_fr": "Mobilier, luminaires, rangement…",             "is_active": True, "display_order": 7},
    {"slug": "beaute",        "name_fr": "Beauté & Santé",   "name_en": "Beauty",      "name_de": "Schönheit",      "icon": "💄", "meta_description_fr": "Soins, maquillage, électro-beauté…",           "is_active": True, "display_order": 8},
]

for cat in CATEGORIES:
    res = sb.table("categories").upsert(cat, on_conflict="slug").execute()
    print(f"  ✅  {cat['icon']}  {cat['name_fr']}")

print(f"\n✅  {len(CATEGORIES)} catégories seedées.")
print("   Lance ensuite : python3 scripts/seed-comparatifs.py")
