#!/usr/bin/env python3
"""
seed-database.py — OBSOLÈTE

Ce script ne sert plus à rien.
Les données viennent maintenant du flux Awin Rue du Commerce.

Utilise à la place :
    python scripts/import-awin-feed.py --help
"""
import sys
print("⛔  seed-database.py est obsolète.")
print()
print("Les données viennent du flux Awin Rue du Commerce.")
print("Utilise :")
print("    python scripts/import-awin-feed.py --reset     # vider la base")
print("    python scripts/import-awin-feed.py --help      # voir toutes les commandes")
sys.exit(0)
