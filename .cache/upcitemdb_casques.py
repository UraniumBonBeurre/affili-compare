import os, requests, time
from pathlib import Path

for line in Path('/Users/nicolasmalpot/Affiliation/affili-compare/.env.local').read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1); os.environ[k.strip()] = v.strip()

URL = os.environ['NEXT_PUBLIC_SUPABASE_URL']
KEY = os.environ['SUPABASE_SERVICE_ROLE_KEY']
TAG = os.environ.get('AMAZON_ASSOCIATE_TAG_FR') or 'afprod-21'
H = {'apikey': KEY, 'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'}

# Products columns
r = requests.get(URL + '/rest/v1/products?limit=1', headers=H)
print('products cols:', list(r.json()[0].keys()))

# Get casques products
r2 = requests.get(URL + '/rest/v1/comparisons?slug=eq.meilleurs-casques-gaming-2026&select=id', headers=H)
comp_id = r2.json()[0]['id']
r3 = requests.get(URL + f'/rest/v1/comparison_products?comparison_id=eq.{comp_id}&select=product_id,position&order=position', headers=H)
cp_list = r3.json()
ids_filter = ','.join(p['product_id'] for p in cp_list)
r4 = requests.get(URL + f'/rest/v1/products?id=in.({ids_filter})&select=id,name,ean,amazon_asin', headers=H)
prods = {p['id']: p for p in r4.json()}

print('\n=== EANs casques ===')
eans = []
for cp in cp_list:
    p = prods.get(cp['product_id'], {})
    ean = p.get('ean') or ''
    print(f'  #{cp["position"]} EAN:{ean} | {p.get("name","")[:50]}')
    if ean:
        eans.append((p['id'], p.get('name',''), ean))

print(f'\n=== UPCItemDB lookup pour {len(eans)} produits ===')
DELAY = 12  # safe for 5/min free tier

for i, (pid, name, ean) in enumerate(eans):
    if i > 0:
        print(f'  (pause {DELAY}s...)')
        time.sleep(DELAY)

    r = requests.get(
        'https://api.upcitemdb.com/prod/trial/lookup',
        params={'upc': ean},
        headers={'Accept': 'application/json'},
        timeout=15
    )
    print(f'\n  [{i+1}/{len(eans)}] {name[:45]}')
    print(f'  HTTP {r.status_code}')
    if r.status_code == 200:
        data = r.json()
        items = data.get('items') or []
        if items:
            item = items[0]
            asin = item.get('asin') or '—'
            title = item.get('title', '')[:50]
            offers = item.get('offers') or []
            prices = [o.get('price') for o in offers if o.get('price')]
            lowest_price = min(prices) if prices else None
            # Extract release date
            pub_date = item.get('published_at') or item.get('date_first_available') or ''
            # Also check metadata fields
            for key in ['released', 'release_date', 'model_year']:
                if item.get(key):
                    pub_date = pub_date or item[key]

            print(f'  ASIN: {asin}')
            print(f'  titre: {title}')
            print(f'  prix: {lowest_price}€ ({len(offers)} offres)')
            print(f'  date: {pub_date}')
            print(f'  toutes clés: {list(item.keys())}')
        else:
            print('  No items found')
            print(f'  response keys: {list(data.keys())}')
            print(f'  message: {data.get("message")}')
    else:
        print(f'  Error: {r.text[:200]}')
