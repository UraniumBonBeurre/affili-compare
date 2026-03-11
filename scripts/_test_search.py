#!/usr/bin/env python3
"""Test de la recherche hybride avec bge-m3."""
import os, sys, requests
from pathlib import Path
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).parent.parent
for line in (ROOT / ".env.local").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

URL = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

print("Chargement bge-m3...")
model = SentenceTransformer("BAAI/bge-m3")
print("OK\n")

QUERIES = [
    # Intent naturelle FR
    ("FR-intent",  "caméra surveillance extérieure sans fil"),
    ("FR-intent",  "aspirateur robot qui lave aussi"),
    ("FR-intent",  "casque sans fil pour gaming"),
    ("FR-intent",  "caméra bébé wifi"),
    # Précis FR
    ("FR-précis",  "Dyson V15"),
    ("FR-précis",  "télévision OLED 55 pouces"),
    ("FR-précis",  "mémoire DDR5"),
    # Intent EN
    ("EN-intent",  "outdoor security camera night vision"),
    ("EN-intent",  "wireless headphones noise cancelling"),
    ("EN-intent",  "robot vacuum mop combo"),
    # Précis EN
    ("EN-précis",  "Imou bullet camera"),
    ("EN-précis",  "Samsung 4K TV"),
    # Fautes FR
    ("FR-typo",    "camera surveillance exterieur san fil"),
    ("FR-typo",    "aspiratuer robot laveur"),
    ("FR-typo",    "caske gaming sans fils"),
    # Courts / tests singulier vs pluriel (régression camera≠cameras)
    ("court",      "camera"),
    ("court",      "cameras"),
    ("court",      "tv"),
    ("court",      "Imou"),
]

SEP = "─" * 72
for qtype, q in QUERIES:
    emb = model.encode(q, normalize_embeddings=True).tolist()
    r = requests.post(
        f"{URL}/rest/v1/rpc/search_products_hybrid",
        headers=H,
        json={"query_embedding": emb, "query_text": q, "match_count": 5},
        timeout=15,
    )
    results = r.json() if r.ok else []
    print(f"\n{SEP}")
    print(f"[{qtype}]  « {q} »")
    if not results:
        print("  (aucun résultat)")
        continue
    for i, p in enumerate(results[:5], 1):
        score = f"{p.get('hybrid_score', 0):.4f}"
        lex   = "LEX" if p.get("in_lexical") else "   "
        brand = (p.get("brand") or "")[:12].ljust(12)
        name  = (p.get("name") or "")[:54]
        cat   = (p.get("category_slug") or "")[:18]
        prix  = p.get("price")
        print(f"  {i}. [{score}] {lex} {brand} | {name}")
        print(f"         cat={cat}  prix={prix}€")

print(f"\n{SEP}\nDone.")
