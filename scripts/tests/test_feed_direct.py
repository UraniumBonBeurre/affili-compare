#!/usr/bin/env python3
"""
Test 4c - Vérifier transactions API + essai accès direct au flux RdC
"""
import os, sys, requests
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env.local")
except ImportError:
    pass

TOKEN  = os.getenv("AWIN_API_TOKEN", "")
PUB_ID = os.getenv("AWIN_PUBLISHER_ID", "")
PROG   = "6901"
H = {"Authorization": f"Bearer {TOKEN}"}

print(f"Token: {TOKEN[:8]}...  Publisher: {PUB_ID}\n")

# 1. Transactions (format correct)
r = requests.get(
    f"https://api.awin.com/publishers/{PUB_ID}/transactions/",
    params={"startDate": "2026-03-01T00:00:00", "endDate": "2026-03-09T23:59:59", "timezone": "Europe/Paris"},
    headers=H, timeout=15
)
print(f"Transactions API → HTTP {r.status_code}")
print(f"  {r.text[:200]}\n")

# 2. Commission groups (lightweight test)
r2 = requests.get(
    f"https://api.awin.com/publishers/{PUB_ID}/commissiongroups?advertiserId={PROG}",
    headers=H, timeout=15
)
print(f"Commission groups RdC → HTTP {r2.status_code}")
print(f"  {r2.text[:300]}\n")

# 3. Essayer accès direct au flux avec quelques feed IDs connus
# (les IDs Awin pour RdC tournent autour de certaines plages)
print("Essai accès direct flux (tentatives avec feed IDs courants):\n")
known_ids = ["655317", "655318", "297765", "297766", "297767", "297768"]
columns = "aw_product_id,product_name,search_price,merchant_deep_link,in_stock"
for fid in known_ids:
    url = (
        f"https://productdata.awin.com/datafeed/download"
        f"/apikey/{TOKEN}/language/fr/fid/{fid}"
        f"/columns/{columns}/format/csv/?limit=5"
    )
    try:
        r3 = requests.get(url, timeout=15)
        if r3.status_code == 200 and "product_name" in r3.text[:500]:
            print(f"  ✅  Feed ID {fid} → HTTP 200 — FLUX TROUVÉ!")
            print(f"      Extrait : {r3.text[:300]}")
            break
        elif r3.status_code == 200:
            print(f"  feed {fid} → HTTP 200 mais format inattendu")
            print(f"  {r3.text[:100]}")
        else:
            print(f"  feed {fid} → HTTP {r3.status_code}")
    except Exception as e:
        print(f"  feed {fid} → erreur: {e}")
