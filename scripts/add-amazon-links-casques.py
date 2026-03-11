#!/usr/bin/env python3
"""
add-amazon-links-casques.py
===========================
Script one-shot pour le Top 5 casques gaming :
  1. Génère amazon_url (recherche par EAN) pour les 5 produits
  2. Insère les affiliate_links Amazon FR dans la bonne comparaison
  3. Déduplique les doubles liens RDC

Lancer avec --dry-run pour prévisualiser.
"""

import os, sys, json, requests
from datetime import datetime, timezone
from pathlib import Path

for line in Path(__file__).resolve().parent.parent.joinpath('.env.local').read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1); os.environ[k.strip()] = v.strip()

URL  = os.environ['NEXT_PUBLIC_SUPABASE_URL']
KEY  = os.environ['SUPABASE_SERVICE_ROLE_KEY']
TAG  = os.environ.get('AMAZON_ASSOCIATE_TAG_FR') or os.environ.get('AMAZON_ASSOCIATE_TAG', 'afprod-21')
H    = {'apikey': KEY, 'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'}
DRY  = '--dry-run' in sys.argv

COMP_SLUG = 'meilleurs-casques-gaming-2026'

def get(path, params=''):
    r = requests.get(f'{URL}/rest/v1/{path}{"?" + params if params else ""}', headers=H, timeout=20)
    r.raise_for_status(); return r.json()

def patch(table, record_id, data):
    r = requests.patch(f'{URL}/rest/v1/{table}?id=eq.{record_id}', headers={**H, 'Prefer': 'return=minimal'}, json=data, timeout=20)
    return r.status_code in (200, 204)

def post(table, data):
    r = requests.post(f'{URL}/rest/v1/{table}', headers={**H, 'Prefer': 'return=representation'}, json=data, timeout=20)
    if r.status_code not in (200, 201): print(f'  ⚠️  POST {table}: {r.status_code} {r.text[:120]}'); return None
    return r.json()

def delete_by_id(table, record_id):
    r = requests.delete(f'{URL}/rest/v1/{table}?id=eq.{record_id}', headers={**H, 'Prefer': 'return=minimal'}, timeout=20)
    return r.status_code in (200, 204)

print(f'\n🎧 Top 5 Casques Gaming — enrichissement Amazon | TAG: {TAG}')
if DRY: print('   Mode DRY-RUN\n')

# ── 1. Récupérer la comparaison ──────────────────────────────────────────────
comp_list = get('comparisons', f'slug=eq.{COMP_SLUG}&select=id,slug,title_fr')
if not comp_list:
    print(f'❌  Comparaison non trouvée : {COMP_SLUG}'); sys.exit(1)
comp = comp_list[0]
print(f'✓ Comparaison : {comp["title_fr"]} (id={comp["id"]})')

# ── 2. Produits de la comparaison ─────────────────────────────────────────────
cp_list = get('comparison_products', f'comparison_id=eq.{comp["id"]}&select=id,position,product_id&order=position')
prod_ids = [p['product_id'] for p in cp_list]
ids_filter = ','.join(prod_ids)

prod_list = get(f'products', f'id=in.({ids_filter})&select=id,name,brand,ean,amazon_asin,amazon_url')
prods = {p['id']: p for p in prod_list}

# ── 3. Affiliate_links existants ──────────────────────────────────────────────
existing_links = get('affiliate_links', f'product_id=in.({ids_filter})&comparison_id=eq.{comp["id"]}&select=id,product_id,partner,url,price')
links_by_prod_partner: dict = {}
for l in existing_links:
    key = (l['product_id'], l['partner'])
    links_by_prod_partner.setdefault(key, []).append(l)

print(f'\n{"─"*60}')
amazon_inserted = 0
rdc_deduped = 0

for cp in cp_list:
    p = prods.get(cp['product_id'], {})
    ean   = p.get('ean') or ''
    name  = p.get('name', '')[:55]
    pid   = p['id']
    print(f'\n#{cp["position"]} {p.get("brand",""):12} | {name}')
    print(f'   EAN: {ean}')

    # ── 3a. Générer amazon_url si absent ──────────────────────────────────────
    amazon_url = p.get('amazon_url') or ''
    if not amazon_url and ean:
        # Lien de recherche par EAN (sans appel UPCItemDB)
        amazon_url = f'https://www.amazon.fr/s?k={ean}&tag={TAG}'
        print(f'   → Génère amazon_url (search) : {amazon_url}')
        if not DRY:
            patch('products', pid, {'amazon_url': amazon_url})
    elif amazon_url:
        print(f'   → amazon_url déjà présente : {amazon_url[:55]}')

    # ── 3b. Insérer affiliate_link Amazon FR ──────────────────────────────────
    amz_key = (pid, 'amazon_fr')
    amz_links = links_by_prod_partner.get(amz_key, [])
    if not amz_links and amazon_url:
        payload = {
            'product_id':     pid,
            'comparison_id':  comp['id'],
            'partner':        'amazon_fr',
            'country':        'fr',
            'url':            amazon_url,
            'price':          None,   # Pas de price API Amazon — affiché "—"
            'currency':       'EUR',
            'in_stock':       True,
            'commission_rate': 3.0,
            'paapi_enabled':  False,
            'last_checked':   datetime.now(timezone.utc).isoformat(),
        }
        print(f'   → INSÈRE lien Amazon : {amazon_url[:55]}')
        if not DRY:
            result = post('affiliate_links', payload)
            if result: amazon_inserted += 1
        else:
            amazon_inserted += 1
    elif amz_links:
        print(f'   ✓ Lien Amazon déjà en base ({len(amz_links)}x)')

    # ── 3c. Dédupliquer les doublons RDC ──────────────────────────────────────
    rdc_key = (pid, 'rue-du-commerce')
    rdc_links = links_by_prod_partner.get(rdc_key, [])
    if len(rdc_links) > 1:
        # Garder le premier, supprimer les suivants
        to_delete = rdc_links[1:]
        print(f'   🗑 Supprime {len(to_delete)} doublon(s) RDC')
        if not DRY:
            for l in to_delete:
                if delete_by_id('affiliate_links', l['id']):
                    rdc_deduped += 1
        else:
            rdc_deduped += len(to_delete)

print(f'\n{"─"*60}')
print(f'✅ Résumé{"  (DRY-RUN)" if DRY else ""}:')
print(f'   Amazon links insérés : {amazon_inserted}/5')
print(f'   Doublons RDC supprimés : {rdc_deduped}')
print(f'\n👀 Visualiser sur : http://localhost:3000/fr/gaming/{COMP_SLUG}')
print(f'   (ou https://affili-compare.vercel.app/fr/gaming/{COMP_SLUG})')
