#!/usr/bin/env python3
"""
create_pinterest_boards.py
──────────────────────────
Crée sur Pinterest tous les boards définis dans data/pinterest_boards.json.
Si un board avec le même nom existe déjà → ignoré (pas de doublon).
Met à jour les board_id dans le fichier JSON après création.

Usage :
    cd /Users/nicolasmalpot/Affiliation/affili-compare
    python3 tests/create_pinterest_boards.py
"""

import json
import sys
import time
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN = "pina_AEAXPIQXABZKCAIAGCAIIDTI7ENKBHABACGSOKN7K6PSO6ZD3W5LBNBOTMY7CKVZQZQJOYLZUGARAW7BF6UF6IBFW5NNV7AA"
API_BASE = "https://api.pinterest.com/v5"
BOARDS_JSON = Path(__file__).parent.parent / "data" / "pinterest_boards.json"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch_existing_boards() -> dict[str, str]:
    """Retourne {nom_board: board_id} pour tous les boards existants du compte."""
    existing: dict[str, str] = {}
    cursor = None
    while True:
        params: dict = {"page_size": 250}
        if cursor:
            params["bookmark"] = cursor
        resp = requests.get(f"{API_BASE}/boards", headers=HEADERS, params=params, timeout=10)
        if resp.status_code == 401:
            print("❌ Token invalide ou expiré.")
            sys.exit(1)
        resp.raise_for_status()
        data = resp.json()
        for b in data.get("items", []):
            existing[b["name"]] = b["id"]
        cursor = data.get("bookmark")
        if not cursor:
            break
    return existing


def create_board(name: str) -> str:
    """Crée un board public et retourne son ID."""
    resp = requests.post(
        f"{API_BASE}/boards",
        headers=HEADERS,
        json={"name": name, "privacy": "PUBLIC"},
        timeout=10,
    )
    if resp.status_code == 401:
        print("❌ Token invalide ou expiré.")
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()["id"]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    config = json.loads(BOARDS_JSON.read_text(encoding="utf-8"))
    boards_cfg = config["boards"]

    print("🔄 Récupération des boards existants…")
    existing = fetch_existing_boards()
    print(f"   {len(existing)} board(s) existant(s) trouvé(s).\n")

    changed = False

    for entry in boards_cfg:
        for lang in ("fr", "en"):
            lang_cfg = entry[lang]
            name = lang_cfg["name"]
            current_id = lang_cfg.get("board_id", "")

            if name in existing:
                board_id = existing[name]
                if current_id != board_id:
                    lang_cfg["board_id"] = board_id
                    changed = True
                print(f"  ⏭  [{lang.upper()}] « {name} » déjà existant → {board_id}")
            else:
                print(f"  ➕  [{lang.upper()}] Création de « {name} »…", end=" ", flush=True)
                try:
                    board_id = create_board(name)
                    lang_cfg["board_id"] = board_id
                    changed = True
                    print(f"✅ {board_id}")
                    time.sleep(0.5)  # petit délai pour éviter le rate-limit
                except requests.HTTPError as e:
                    print(f"❌ {e.response.status_code}: {e.response.text[:200]}")

    if changed:
        BOARDS_JSON.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n✅ {BOARDS_JSON.name} mis à jour avec les board_id.")
    else:
        print("\n✔  Aucune modification nécessaire.")


if __name__ == "__main__":
    main()
