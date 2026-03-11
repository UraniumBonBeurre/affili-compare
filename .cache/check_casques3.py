import os, requests
from pathlib import Path

for line in Path('/Users/nicolasmalpot/Affiliation/affili-compare/.env.local').read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k.strip()] = v.strip()

URL = os.environ['NEXT_PUBLIC_SUPABASE_URL']
KEY = os.environ['SUPABASE_SERVICE_ROLE_KEY']
H = {'apikey': KEY, 'Authorization': 'Bearer ' + KEY}

# Get the casques gaming comparison
r = requests.get(f'{URL}/rest/v1/comparisons?slug=eq.meilleurs-casques-gaming-2026&select=id,slug,title_fr', headers=H)
comp = r.json()[0]
print(f'Comparison: {comp["title_fr"]} ({comp["slug"]})')

# Get products with position
r2 = requests.get(f'{URL}/rest/v1/comparison_products?comparison_id=eq.{comp["id"]}&select=id,position,product_id&order=position', headers=H)
cp_list = r2.json()
prod_ids = [p['product_id'] for p in cp_list]
ids_filter = ','.join(prod_ids)

# Get product details
r3 = requests.get(f'{URL}/rest/v1/products?id=in.({ids_filter})&select=id,name,brand,ean,amazon_asin,amazon_url,image_url', headers=H)
prods = {p['id']: p for p in r3.json()}

# Get affiliate_links for these products
r4 = requests.get(f'{URL}/rest/v1/affiliate_links?product_id=in.({ids_filter})&select=id,product_id,partner,price,currency,url,in_stock&order=price.asc', headers=H)
links = r4.json()
print(f'\naffiliate_links schema sample: {list(links[0].keys()) if links else "NONE"}')

links_by_prod = {}
for l in links:
    links_by_prod.setdefault(l['product_id'], []).append(l)

print(f'\n{"="*70}')
for cp in cp_list:
    p = prods.get(cp['product_id'], {})
    prod_links = links_by_prod.get(cp['product_id'], [])
    print(f'\n#{cp["position"]} {p.get("brand",""):12} | {p.get("name","")[:55]}')
    ean = p.get("ean") or "—"; asin = p.get("amazon_asin") or "—"
    print(f'  EAN: {ean:15} ASIN: {asin:12} amz_url: {"OUI" if p.get("amazon_url") else "NON"}')
    if prod_links:
        for l in prod_links:
            print(f'  link [{l["partner"]:20}] {(l["price"] or 0):7.2f}€ in_stock={l["in_stock"]} url:{l["url"][:60]}')
    else:
        print(f'  ⚠️  AUCUN lien affilié!')
