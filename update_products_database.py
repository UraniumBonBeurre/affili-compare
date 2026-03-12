#!/usr/bin/env python3
"""
update_products_database.py — Wrapper quotidien pour la mise à jour des produits
==================================================================================

Appelé par le GitHub Action update_products_database.yaml.
Exécute recup_flux_awin.py en mode update pour tous les marchands actifs.

Usage :
    python3 update_products_database.py
    python3 update_products_database.py --dry-run
"""

import os
import subprocess
import sys
from pathlib import Path


def main():
    script = Path(__file__).parent / "recup_flux_awin.py"

    # Mode : env var (set by GitHub Actions via input) ou fallback CLI
    mode = os.environ.get("IMPORT_MODE", "update")
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        mode = sys.argv[idx + 1]

    cmd = [sys.executable, str(script), "--mode", mode]

    # Limit par marchand (uniquement utile pour reset_and_fill)
    if mode == "reset_and_fill":
        max_count = os.environ.get("MAX_PER_MERCHANT", "1000")
        cmd += ["--count", max_count]

    if "--dry-run" in sys.argv:
        cmd.append("--dry-run")

    print(f"🚀  Lancement : {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
