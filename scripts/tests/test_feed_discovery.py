#!/usr/bin/env python3
"""
Test 4b - Essayer plusieurs endpoints Awin pour trouver le feed ID
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

headers_auth = {"Authorization": f"Bearer {TOKEN}"}

endpoints = [
    # 1. ProductData list with explicit json format
    ("productdata list json",
     f"https://productdata.awin.com/datafeed/list/apikey/{TOKEN}/format/json/",
     {}),
    # 2. ProductData list with xml format
    ("productdata list xml",
     f"https://productdata.awin.com/datafeed/list/apikey/{TOKEN}/format/xml/",
     {}),
    # 3. Publisher API feeds endpoint
    ("api.awin publisher feeds",
     f"https://api.awin.com/publishers/{PUB_ID}/feeds",
     headers_auth),
    # 4. Publisher API productfeeds
    ("api.awin publisher productfeeds",
     f"https://api.awin.com/publishers/{PUB_ID}/productfeeds",
     headers_auth),
    # 5. Publisher API feeds filtered by programme
    ("api.awin feeds?advertiserIds",
     f"https://api.awin.com/publishers/{PUB_ID}/feeds?advertiserIds={PROG}",
     headers_auth),
    # 6. Old style advertiser endpoint
    ("api.awin transactions (ping)",
     f"https://api.awin.com/publishers/{PUB_ID}/transactions/?startDate=2026-01-01&endDate=2026-01-02&timezone=Europe%2FParis",
     headers_auth),
]

for name, url, hdrs in endpoints:
    try:
        r = requests.get(url, headers=hdrs, timeout=15)
        preview = r.text[:200].replace("\n", " ")
        print(f"\n{'─'*60}")
        print(f"  {name}")
        print(f"  HTTP {r.status_code}")
        print(f"  {preview}")
    except Exception as e:
        print(f"\n  {name} → ERREUR : {e}")
