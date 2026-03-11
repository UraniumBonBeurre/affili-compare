import os, requests, json
from pathlib import Path
for line in Path('.env.local').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k,v = line.split('=',1); os.environ[k.strip()] = v.strip()
URL = os.environ['NEXT_PUBLIC_SUPABASE_URL']
KEY = os.environ['SUPABASE_SERVICE_ROLE_KEY']
H = {'apikey': KEY, 'Authorization': f'Bearer {KEY}'}

r = requests.get(f'{URL}/rest/v1/comparisons?slug=eq.meilleurs-casques-audio-2026-03&select=id,title,slug', headers=H)
comp = r.json()[0] if r.json() else None
print('Comparison:', json.dumps(comp, indent=2))
if comp:
    r2 = requests.get(f'{URL}/rest/v1/comparison_products?comparison_id=eq.{comp["id"]}&select=rank,product_id,affiliate_url&order=rank', headers=H)
    cp_list = r2.json()
    prods_ids = [p['product_id'] for p in cp_list]
    print(f'\n{len(prods_ids)} produits dans la comparaison')
    ids_filter = ','.join(prods_ids)
    r3 = requests.get(f'{URL}/rest/v1/products?id=in.({ids_filter})&select=id,name,brand,ean,amazon_asin,amazon_url,image_url,search_price', headers=H)
    prods = {p['id']: p for p in r3.json()}
    for cp in cp_list:
        p = prods.get(cp['product_id'], {})
        print(f"  #{cp['rank']} {p.get('brand','')} | {p.get('name','')[:45]} | EAN:{p.get('ean','—')} | ASIN:{p.get('amazon_asin','—')} | amz_url:{('OUI: '+p.get('amazon_url','')[:30]) if p.get('amazon_url') else '—'}")
        print(f"       awin_url: {(cp.get('affiliate_url') or '')[:60]}")
