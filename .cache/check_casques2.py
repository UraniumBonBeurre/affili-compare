import os, requests
from pathlib import Path

for line in Path('/Users/nicolasmalpot/Affiliation/affili-compare/.env.local').read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k.strip()] = v.strip()

URL = os.environ['NEXT_PUBLIC_SUPABASE_URL']
KEY = os.environ['SUPABASE_SERVICE_ROLE_KEY']
H = {'apikey': KEY, 'Authorization': f'Bearer {KEY}'}

r = requests.get(f'{URL}/rest/v1/comparisons?select=id,slug,title_fr,is_published', headers=H)
comps = r.json()
print('=== COMPARISONS ===')
for c in comps:
    print(f'  published={c["is_published"]} | {c["slug"]} | {c["title_fr"]}')

casque_comps = [c for c in comps if 'casques' in c['slug'] or 'audio' in c['slug']]
if not casque_comps:
    print('\nAucune comp casques trouvée')
    exit()

comp = casque_comps[0]
print(f'\n=== PRODUCTS in {comp["slug"]} ===')
r2 = requests.get(
    f'{URL}/rest/v1/comparison_products?comparison_id=eq.{comp["id"]}&select=position,product_id&order=position',
    headers=H
)
cp_list = r2.json()
print(f'{len(cp_list)} produits')

if cp_list:
    ids = ','.join(p['product_id'] for p in cp_list)
    r3 = requests.get(
        f'{URL}/rest/v1/products?id=in.({ids})&select=id,name,brand,ean,amazon_asin,amazon_url,image_url',
        headers=H
    )
    if r3.status_code != 200:
        print('Error products:', r3.status_code, r3.text[:200])
        exit(1)
    prods = {p['id']: p for p in r3.json()}
    for cp in cp_list:
        p = prods.get(cp['product_id'], {})
        amz = p.get('amazon_url') or '—'
        print(f'  #{cp["position"]} {p.get("brand","")[:12]} | {p.get("name","")[:50]}')
        print(f'       price:{p.get("search_price","—")} | ean:{p.get("ean","—")} | amz:{amz[:50]}')
