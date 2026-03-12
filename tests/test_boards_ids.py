#!/usr/bin/env python3
"""
pinterest_boards.py
────────────────────
Récupère tous tes boards Pinterest (nom + ID) via l'API v5.

Usage :
    export PINTEREST_TOKEN="ton_token"
    python3 pinterest_boards.py

    # Ou directement :
    PINTEREST_TOKEN="ton_token" python3 pinterest_boards.py

Pré-requis :
    pip install requests
"""

import os
import sys
import requests

TOKEN = 'pina_AEAXPIQXABZKCAIAGCAIIDTI7ENKBHABACGSOKN7K6PSO6ZD3W5LBNBOTMY7CKVZQZQJOYLZUGARAW7BF6UF6IBFW5NNV7AA'
API_BASE = "https://api.pinterest.com/v5"


def fetch_all_boards(token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    boards = []
    cursor = None

    while True:
        params = {"page_size": 250}
        if cursor:
            params["bookmark"] = cursor

        resp = requests.get(f"{API_BASE}/boards", headers=headers, params=params, timeout=10)

        if resp.status_code == 401:
            print("❌ Token invalide ou expiré.")
            sys.exit(1)

        resp.raise_for_status()
        data = resp.json()

        boards.extend(data.get("items", []))

        cursor = data.get("bookmark")
        if not cursor:
            break

    return boards


def main():
    if not TOKEN:
        print("❌ Token manquant. Lance : export PINTEREST_TOKEN='ton_token'")
        sys.exit(1)

    print("🔄 Récupération des boards...\n")
    boards = fetch_all_boards(TOKEN)

    if not boards:
        print("Aucun board trouvé.")
        return

    # Affichage aligné
    max_len = max(len(b["name"]) for b in boards)
    print(f"{'Nom':<{max_len}}  ID")
    print("─" * (max_len + 22))
    for b in boards:
        print(f"{b['name']:<{max_len}}  {b['id']}")

    print(f"\n✅ {len(boards)} board(s) trouvé(s).")


if __name__ == "__main__":
    main()