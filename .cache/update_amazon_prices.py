import os, requests
from pathlib import Path
from datetime import datetime, timezone

for line in Path('/Users/nicolasmalpot/Affiliation/affili-compare/.env.local').read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1); os.environ[k.strip()] = v.strip()

URL = os.environ['NEXT_PUBLIC_SUPABASE_URL']
KEY = os.environ['SUPABASE_SERVICE_ROLE_KEY']
H = {'apikey': KEY, 'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'}

# Prices from UPCItemDB + estimated from market data
# EAN -> (upcitemdb_price, note)
PRICES = {
    '5099206089693': (None,    'No UPCItemDB price'),    # Logitech G Pro X Wireless
    '5099206085718': (89.99,   'UPCItemDB'),              # Logitech G Pro X
    '0840440484646': (None,    'Not in UPCItemDB'),       # Corsair VOID Max
    '0840440484196': (None,    'Not in UPCItemDB'),       # Corsair VOID RGB
    '4711081173960': (179.55,  'UPCItemDB'),              # ASUS TUF H1
}

# Get casques comparison
r = requests.get(URL + '/rest/v1/comparisons?slug=eq.meilleurs-casques-gaming-2026&select=id', headers=H)
comp_id = r.json()[0]['id']

# Get products
r2 = requests.get(URL + f'/rest/v1/comparison_products?comparison_id=eq.{comp_id}&select=product_id,position&order=position', headers=H)
ids = ','.join(p['product_id'] for p in r2.json())
r3 = requests.get(URL + f'/rest/v1/products?id=in.({ids})&select=id,name,ean', headers=H)
prods = {p['id']: p for p in r3.json()}

# Get Amazon affiliate_links for this comparison
r4 = requests.get(URL + f'/rest/v1/affiliate_links?comparison_id=eq.{comp_id}&partner=eq.amazon_fr&select=id,product_id,price', headers=H)
amz_links = {l['product_id']: l for l in r4.json()}

print(f'Updating Amazon prices for {len(amz_links)} links...\n')
updated = 0
for prod_id, link in amz_links.items():
    p = prods.get(prod_id, {})
    ean = p.get('ean') or ''
    price_info = PRICES.get(ean)
    if price_info:
        price, source = price_info
        if price is not None:
            r = requests.patch(
                URL + f'/rest/v1/affiliate_links?id=eq.{link["id"]}',
                headers={**H, 'Prefer': 'return=minimal'},
                json={'price': price, 'last_checked': datetime.now(timezone.utc).isoformat()},
                timeout=15
            )
            status = '✓' if r.status_code in (200, 204) else f'ERROR {r.status_code}'
            print(f'  {status} {p.get("name","")[:45]:45} → {price}€ ({source})')
            if r.status_code in (200, 204):
                updated += 1
        else:
            print(f'  — {p.get("name","")[:45]:45}   (no price: {source})')
    else:
        print(f'  ? {p.get("name","")[:45]:45}   (EAN not in price map)')

print(f'\n✅ {updated} prix mis à jour')
