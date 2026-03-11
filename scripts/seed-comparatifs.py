#!/usr/bin/env python3
"""
seed-comparatifs.py — Crée plusieurs comparatifs depuis le flux RdC en une passe.
Usage: python3 scripts/seed-comparatifs.py
"""
import subprocess, sys, os
from pathlib import Path

BASE = Path(__file__).parent.parent

COMPARATIFS = [
    # (category_slug, subcategory, query, feed_category, min_price, limit, slug, title)
    # ── Informatique ──
    ("informatique", "PC portable",  "",        "PC portable",  400.0, 5, "meilleurs-pc-portables-2026",         "Top 5 PC portables 2026"),
    ("informatique", "Clavier",      "clavier", "Clavier",       20.0, 5, "meilleurs-claviers-2026",             "Top 5 claviers PC 2026"),
    ("informatique", "SSD",          "",        "SSD",           30.0, 5, "meilleurs-ssd-2026",                  "Top 5 SSD internes 2026"),
    ("informatique", "Souris",       "",        "Souris",        10.0, 5, "meilleures-souris-pc-2026",           "Top 5 souris PC 2026"),
    # ── Gaming ──
    ("gaming",       "Fauteuil",     "",        "Fauteuil gamer", 200.0, 5, "meilleurs-fauteuils-gaming-2026",   "Top 5 fauteuils gaming 2026"),
    ("gaming",       "Casque",       "gaming",  "Micro-casque",   30.0, 5, "meilleurs-casques-gaming-2026",      "Top 5 casques gaming 2026"),
    # ── TV & Hi-Fi ──
    ("tv-hifi",      "Téléviseur",   "",        "TV",            300.0, 5, "meilleures-tv-4k-2026",              "Top 5 TV 4K 2026"),
    ("tv-hifi",      "Enceinte BT",  "",        "Enceinte bluetooth", 50.0, 5, "meilleures-enceintes-bluetooth-2026", "Top 5 enceintes bluetooth 2026"),
    # ── Smartphone ──
    ("smartphone",   "Android",      "Samsung", "Smartphone Android", 200.0, 5, "meilleurs-smartphones-android-2026", "Top 5 smartphones Android 2026"),
]

script = BASE / "scripts" / "import-awin-feed.py"
python = sys.executable

errors = []
for i, (cat, sub, query, feed_cat, min_price, limit, slug, title) in enumerate(COMPARATIFS, 1):
    print(f"\n{'='*60}")
    print(f"  [{i}/{len(COMPARATIFS)}] {title}")
    print(f"{'='*60}")
    cmd = [
        python, str(script),
        "--create-comparison",
        "--query", query,
        "--limit", str(limit),
        "--slug", slug,
        "--title", title,
        "--category", cat,
        "--subcategory", sub,
        "--feed-category", feed_cat,
        "--min-price", str(min_price),
    ]
    result = subprocess.run(cmd, cwd=str(BASE))
    if result.returncode != 0:
        errors.append(title)

print(f"\n{'='*60}")
if errors:
    print(f"⚠  {len(errors)} erreur(s) :")
    for e in errors:
        print(f"   • {e}")
else:
    print(f"✅  {len(COMPARATIFS)} comparatifs créés avec succès !")
