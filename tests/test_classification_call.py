#!/usr/bin/env python3
"""
Test direct: appel classification avec gpt-oss:20b-cloud via curl subprocess
"""

import json, time, sys, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from settings import OLLAMA_CLOUD_API_KEY, OLLAMA_CLOUD_HOST, CLASSIFICATION_LLM

SYSTEM = """Tu es un classificateur de produits e-commerce. Classe chaque produit.
FORMAT: {"results": [{"id": "ID", "product_type": "smartphone", "room": "universel", "use_category": "accessoire", "niches": []}]}
Retourne UNIQUEMENT du JSON valide."""

PRODUCTS = [
    {"id": "1", "name": "iPhone 15 Pro", "brand": "Apple", "category_slug": "tech", "merchant_category": "Smartphones", "description": "Dernier iPhone avec puce A17"},
    {"id": "2", "name": "Samsung Galaxy S24", "brand": "Samsung", "category_slug": "tech", "merchant_category": "Smartphones", "description": "Flagship 2024"},
    {"id": "3", "name": "AirPods Pro", "brand": "Apple", "category_slug": "audio", "merchant_category": "Casques", "description": "Ecouteurs sans fil ANC"},
]

payload = {
    "model": CLASSIFICATION_LLM,
    "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(PRODUCTS, ensure_ascii=False)}
    ],
    "stream": False,
    "think": False,
}

print(f"Model: {CLASSIFICATION_LLM}")
print(f"Via: curl subprocess (HTTP/2)")
print(f"Appel en cours...")

t0 = time.time()
result = subprocess.run(
    [
        "curl", "-s", "-X", "POST",
        f"{OLLAMA_CLOUD_HOST}/api/chat",
        "-H", f"Authorization: Bearer {OLLAMA_CLOUD_API_KEY}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps(payload, ensure_ascii=False),
        "--max-time", "60",
    ],
    capture_output=True, text=True, timeout=70,
)
elapsed = time.time() - t0

print(f"Terminé en {elapsed:.1f}s — rc={result.returncode}")
if result.returncode != 0 or not result.stdout:
    print(f"Erreur: {result.stderr[:300]}")
    sys.exit(1)

data = json.loads(result.stdout)
content = data.get("message", {}).get("content", "")
thinking = data.get("message", {}).get("thinking", "")
print(f"Contenu ({len(content)} chars):\n{content[:500]}")
if thinking:
    print(f"  ⚠️  Thinking tokens présents ({len(thinking)} chars)")
