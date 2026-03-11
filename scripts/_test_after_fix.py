"""
Test à lancer APRÈS avoir appliqué la migration 20260310_fix_or_query.sql :
  → Vérifie que camera/cameras retournent les mêmes résultats Imou
  → Vérifie la régressions : aspirateur robot, imou bullet, DDR5...
"""
import os, requests
from pathlib import Path
from sentence_transformers import SentenceTransformer

root = Path("/Users/nicolasmalpot/Affiliation/affili-compare")
for line in (root / ".env.local").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

URL = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

print("Chargement bge-m3...")
model = SentenceTransformer("BAAI/bge-m3")
print("OK\n")

# Synonymes simulés (comme parseQuery le ferait)
SYNONYMS = {
    "camera":      "camera appareil webcam",
    "cameras":     "camera appareil webcam",
    "caméra":      "camera appareil webcam",
    "tv":          "TV television ecran",
    "aspirateur":  "aspirateur robot vacuum",
}

CASES = [
    # (label, raw_query, query_text_for_fts)
    ("camera [singulier]",     "camera",                              SYNONYMS["camera"]),
    ("cameras [pluriel]",      "cameras",                             SYNONYMS["cameras"]),
    ("caméra surveillance",    "caméra surveillance extérieure",      "camera appareil webcam surveillance exterieure"),
    ("caméra bébé",            "caméra bébé wifi",                   "camera appareil webcam bebe wifi"),
    ("imou bullet",            "imou bullet camera",                  "imou bullet camera appareil webcam"),
    ("aspirateur robot",       "aspirateur robot qui lave",           SYNONYMS["aspirateur"] + " lave"),
    ("TV OLED",                "télévision OLED 55 pouces",           SYNONYMS["tv"] + " oled 55 pouces"),
    ("DDR5",                   "mémoire DDR5",                        "ddr5 memoire"),
]

SEP = "─" * 68
for label, raw_q, query_text in CASES:
    emb = model.encode(raw_q, normalize_embeddings=True).tolist()
    r = requests.post(
        f"{URL}/rest/v1/rpc/search_products_hybrid",
        headers=H,
        json={"query_embedding": emb, "query_text": query_text, "match_count": 5},
        timeout=15,
    )
    results = r.json() if r.ok else []
    lex_count = sum(1 for p in results if p.get("in_lexical"))
    print(f"\n{SEP}")
    print(f"[{label}]  raw='{raw_q}'  lex_matches={lex_count}/{len(results)}")
    if not r.ok:
        print(f"  ERROR {r.status_code}: {r.text[:200]}")
        continue
    for p in results[:5]:
        score = p.get("hybrid_score", 0)
        lex = "LEX" if p.get("in_lexical") else "   "
        brand = (p.get("brand") or "")[:12].ljust(12)
        name = (p.get("name") or "")[:52]
        prix = p.get("price")
        print(f"  [{score:.4f}] {lex} {brand} | {name}  prix={prix}")

print(f"\n{SEP}\nDone.")
