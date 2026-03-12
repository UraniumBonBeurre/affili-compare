#!/usr/bin/env python3
"""
update_products_database.py — Wrapper quotidien pour la mise à jour des produits
==================================================================================

Appelé par le GitHub Action update_products_database.yaml.
Exécute recup_flux_awin.py en mode update pour tous les marchands actifs.
Enchaîne ensuite classification.py et create_embeddings.py.

Usage :
    python3 update_products_database.py
    python3 update_products_database.py --dry-run
"""

import subprocess
import sys
from pathlib import Path
import os

def run(cmd: list[str], label: str) -> None:
    print(f"\n{'─'*60}")
    print(f"🚀  {label}")
    print(f"    {' '.join(cmd)}")
    print(f"{'─'*60}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"❌  {label} a échoué (code {result.returncode})")
        sys.exit(result.returncode)


def main():
    root = Path(__file__).parent
    dry_run = "--dry-run" in sys.argv

    # ── 1. Import flux ────────────────────────────────────────────────────────
    mode = os.environ.get("IMPORT_MODE", "update")
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        mode = sys.argv[idx + 1]

    import_cmd = [sys.executable, str(root / "recup_flux_awin.py"), "--mode", mode]
    if mode == "reset_and_fill":
        max_count = "1000"
        if "--count" in sys.argv:
            max_count = sys.argv[sys.argv.index("--count") + 1]
        import_cmd += ["--count", max_count]
    if dry_run:
        import_cmd.append("--dry-run")

    run(import_cmd, f"Import flux ({mode})")

    if dry_run:
        print("\n[DRY-RUN] Classification et embeddings ignorés.")
        return

    # ── 2. Classification LLM ─────────────────────────────────────────────────
    run(
        [sys.executable, str(root / "classification.py")],
        "Classification LLM des nouveaux produits",
    )

    # ── 3. Embeddings vectoriels ──────────────────────────────────────────────
    run(
        [sys.executable, str(root / "create_embeddings.py")],
        "Génération des embeddings vectoriels",
    )

    print("\n✅  Pipeline complet terminé.")


if __name__ == "__main__":
    main()
