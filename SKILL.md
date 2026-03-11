---
name: affili-compare
description: Build and iterate on a fully automated affiliate comparison website. Use this skill for any task related to: creating comparison pages, setting up Supabase schema, configuring Cloudflare R2 image storage, deploying on Vercel, automating Pinterest publishing via GitHub Actions, generating content with LLMs (Hugging Face / Ollama), or managing multi-partner affiliate links. Trigger on tasks like "add a new product category", "generate comparison content", "set up Pinterest automation", "create affiliate page", "update database schema", or "optimize conversion".
metadata:
  author: Volaille Suprême
  version: 1.0.0
  category: affiliate-marketing
  tags: [nextjs, supabase, cloudflare-r2, vercel, github-actions, pinterest, affiliate, llm]
---

# AffiliCompare — Skill de développement

Tu construis **AffiliCompare**, un site de comparatifs produits multi-affiliés, entièrement automatisé, international, et orienté conversion maximale.

---

## Vision du projet

Un visiteur arrive depuis une épingle Pinterest (visuel IA + titre accrocheur). Il atterrit sur une page comparatif claire, bien structurée, qui compare 5 à 10 produits de **différentes marques et enseignes** (Amazon FR/UK/US/DE, Cdiscount, Fnac, Darty, eBay, etc.). Il clique sur un lien affilié, achète, et une commission est générée — **sans intervention manuelle**.

Le moteur de croissance : **Pinterest → Site → Affiliation × N partenaires**.

---

## Stack technique (tout gratuit au départ)

| Couche | Outil | Rôle |
|---|---|---|
| Frontend | Next.js 14 (App Router) | SSG/ISR, SEO, performance |
| Base de données | Supabase (PostgreSQL) | Produits, catégories, liens affiliés |
| Stockage images | Cloudflare R2 | Visuels IA générés |
| Hébergement | Vercel (free tier) | CI/CD automatique depuis GitHub |
| Automation | GitHub Actions | Cron jobs Pinterest + génération contenu |
| LLM texte | Ollama (local) ou Hugging Face Inference API | Génération descriptions, titres SEO |
| LLM images | Hugging Face (FLUX ou SDXL) | Visuels déco IA pour épingles |
| Pinterest | Pinterest API v5 | Publication automatique des épingles |
| Affiliations | Amazon Associates + Awin + ShareASale + directs | Liens tracés multi-plateformes |

---

## Architecture des fichiers

```
affili-compare/
├── SKILL.md                          ← CE FICHIER (ne pas supprimer)
├── .env.local                        ← Variables secrètes (jamais commitées)
├── .env.example                      ← Template variables d'environnement
├── next.config.js
├── package.json
│
├── app/                              ← Next.js App Router
│   ├── layout.tsx                    ← Layout global (header, footer, trust signals)
│   ├── page.tsx                      ← Homepage (catégories vedettes)
│   ├── [category]/
│   │   ├── page.tsx                  ← Page liste d'une catégorie
│   │   └── [slug]/
│   │       └── page.tsx              ← Page comparatif individuelle
│   ├── sitemap.ts                    ← Sitemap dynamique
│   └── robots.ts
│
├── components/
│   ├── ComparisonTable.tsx           ← Tableau comparatif (cœur du site)
│   ├── ProductCard.tsx               ← Carte produit avec lien affilié
│   ├── AffiliateButton.tsx           ← Bouton CTA avec tracking
│   ├── TrustBadges.tsx               ← Éléments de confiance
│   ├── CategoryGrid.tsx              ← Grille des catégories
│   └── PriceTag.tsx                  ← Affichage prix formaté
│
├── lib/
│   ├── supabase.ts                   ← Client Supabase
│   ├── r2.ts                         ← Client Cloudflare R2
│   ├── affiliate-links.ts            ← Génération liens affiliés trackés
│   ├── seo.ts                        ← Métadonnées SEO dynamiques
│   └── i18n.ts                       ← Internationalisation (fr/en/de)
│
├── scripts/                          ← Exécutés par GitHub Actions
│   ├── generate-content.py           ← Génère comparatifs via LLM
│   ├── generate-images.py            ← Génère visuels Pinterest via HF
│   ├── publish-pinterest.py          ← Publie épingles sur Pinterest
│   ├── update-prices.py              ← Met à jour les prix depuis les APIs
│   └── seed-database.py             ← Peuple Supabase avec nouveaux produits
│
├── .github/
│   └── workflows/
│       ├── publish-pinterest.yml     ← Cron: 3x/jour, publie 10 épingles
│       ├── generate-content.yml      ← Cron: 1x/semaine, nouveaux comparatifs
│       └── update-prices.yml         ← Cron: 1x/jour, refresh prix
│
└── supabase/
    └── migrations/
        └── 001_initial_schema.sql    ← Schéma complet de la BDD
```

---

## Schéma Supabase (à implémenter en priorité)

```sql
-- Catégories de produits
CREATE TABLE categories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT UNIQUE NOT NULL,           -- "aspirateurs-sans-fil"
  name_fr TEXT NOT NULL,
  name_en TEXT,
  name_de TEXT,
  meta_description_fr TEXT,
  pinterest_board_id TEXT,             -- Board Pinterest dédié
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Pages comparatifs
CREATE TABLE comparisons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT UNIQUE NOT NULL,           -- "meilleurs-aspirateurs-sans-fil-2026"
  category_id UUID REFERENCES categories(id),
  title_fr TEXT NOT NULL,
  title_en TEXT,
  intro_fr TEXT,                       -- Intro générée par LLM
  buying_guide_fr TEXT,                -- Guide d'achat LLM
  faq_fr TEXT,                         -- FAQ générée LLM (JSON array)
  last_updated TIMESTAMPTZ DEFAULT now(),
  is_published BOOLEAN DEFAULT false,
  seo_score INTEGER,                   -- Score qualité 0-100
  monthly_views INTEGER DEFAULT 0
);

-- Produits individuels
CREATE TABLE products (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  brand TEXT NOT NULL,
  image_r2_key TEXT,                   -- Clé dans Cloudflare R2
  image_url TEXT,                      -- URL publique R2
  rating DECIMAL(3,1),                 -- Note moyenne (1-5)
  review_count INTEGER,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Liens affiliés par partenaire et pays
CREATE TABLE affiliate_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id UUID REFERENCES products(id),
  comparison_id UUID REFERENCES comparisons(id),
  partner TEXT NOT NULL,               -- "amazon_fr", "cdiscount", "fnac", "ebay_de"
  country TEXT NOT NULL,               -- "fr", "uk", "de", "us"
  url TEXT NOT NULL,                   -- Lien affilié complet
  price DECIMAL(10,2),
  currency TEXT DEFAULT 'EUR',
  in_stock BOOLEAN DEFAULT true,
  commission_rate DECIMAL(5,2),        -- % commission
  last_checked TIMESTAMPTZ DEFAULT now()
);

-- Épingles Pinterest publiées
CREATE TABLE pinterest_pins (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  comparison_id UUID REFERENCES comparisons(id),
  pin_id TEXT,                         -- ID retourné par API Pinterest
  image_r2_key TEXT,
  title TEXT,
  description TEXT,
  published_at TIMESTAMPTZ,
  impressions INTEGER DEFAULT 0,
  clicks INTEGER DEFAULT 0,
  board_id TEXT
);

-- Row Level Security
ALTER TABLE comparisons ENABLE ROW LEVEL SECURITY;
ALTER TABLE affiliate_links ENABLE ROW LEVEL SECURITY;

-- Lectures publiques autorisées
CREATE POLICY "Public read" ON comparisons FOR SELECT USING (is_published = true);
CREATE POLICY "Public read" ON affiliate_links FOR SELECT USING (true);
```

---

## Variables d'environnement (.env.example)

```bash
# Supabase
NEXT_PUBLIC_SUPABASE_URL=https://xxxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...      # Scripts Python uniquement

# Cloudflare R2
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=affili-compare-images
R2_PUBLIC_URL=https://pub-xxx.r2.dev  # URL publique du bucket

# Hugging Face
HF_API_TOKEN=hf_xxx                   # Pour génération images FLUX/SDXL
HF_TEXT_MODEL=mistralai/Mixtral-8x7B-Instruct-v0.1

# Ollama (si local)
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=mistral

# Pinterest API
PINTEREST_ACCESS_TOKEN=
PINTEREST_BOARD_ID_FR=
PINTEREST_BOARD_ID_EN=

# Affiliations
AMAZON_ASSOCIATE_TAG_FR=monsite-21
AMAZON_ASSOCIATE_TAG_DE=monsite-23
AMAZON_ASSOCIATE_TAG_UK=monsite-22
AMAZON_ASSOCIATE_TAG_US=monsite0a-20

# Vercel
VERCEL_TOKEN=                         # Pour revalidation ISR
```

---

## Composant clé : ComparisonTable.tsx

Ce composant est **le cœur de la conversion**. Il doit :
- Afficher un tableau responsive avec colonnes : Produit / Prix / Note / Points forts / Lien
- Highlighter le "Meilleur rapport qualité/prix" et le "Coup de cœur"
- Afficher les prix de **plusieurs partenaires** pour le même produit (comparer Amazon vs Fnac vs Cdiscount)
- Boutons d'achat gros, colorés par partenaire (orange Amazon, rouge Fnac, etc.)
- Mise à jour des prix en temps réel via ISR (revalidate: 3600)
- Disclosure affilié légal visible en haut

```tsx
// Structure attendue des props
interface ComparisonTableProps {
  products: {
    id: string
    name: string
    brand: string
    imageUrl: string
    rating: number
    reviewCount: number
    badge?: "best-value" | "premium" | "budget"
    pros: string[]
    cons: string[]
    links: {
      partner: string       // "Amazon FR", "Fnac", "Cdiscount"
      price: number
      currency: string
      url: string
      inStock: boolean
    }[]
  }[]
  locale: "fr" | "en" | "de"
}
```

---

## Scripts d'automatisation (GitHub Actions)

### generate-images.py
```python
"""
Génère des visuels Pinterest pour une comparaison donnée.
Utilise Hugging Face FLUX pour le rendu IA.
Stocke dans Cloudflare R2, retourne l'URL publique.

Prompt template Pinterest :
"Luxurious {category} product flat lay, interior design style,
white background, professional photography, text overlay space,
Pinterest aesthetic, high resolution"
"""
```

### publish-pinterest.py
```python
"""
Publie 10 épingles par run via Pinterest API v5.
Sélectionne les comparaisons non encore épinglées depuis 7 jours.
Format titre : "Top {N} {category} 2026 – Comparatif & Prix"
Format description : 200 chars avec appel à l'action + mots-clés
Enregistre le pin_id dans Supabase pour tracking.
"""
```

### generate-content.py
```python
"""
Génère du contenu pour une nouvelle page comparatif :
1. Prompt LLM pour intro (300 mots, ton expert, mots-clés naturels)
2. Prompt LLM pour guide d'achat (500 mots, critères de choix)
3. Prompt LLM pour FAQ (5 questions/réponses, schema FAQ)
4. Met à jour Supabase + déclenche revalidation Vercel ISR
Utilise Ollama en local ou HF Inference API selon disponibilité.
"""
```

---

## GitHub Actions Workflows

### publish-pinterest.yml
```yaml
name: Publish Pinterest Pins
on:
  schedule:
    - cron: '0 8,14,20 * * *'   # 3x par jour
  workflow_dispatch:              # Déclenchement manuel possible
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with: { python-version: '3.11' }
      - run: pip install requests boto3 supabase
      - run: python scripts/generate-images.py
      - run: python scripts/publish-pinterest.py
    env:
      HF_API_TOKEN: ${{ secrets.HF_API_TOKEN }}
      PINTEREST_ACCESS_TOKEN: ${{ secrets.PINTEREST_ACCESS_TOKEN }}
      SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
      R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
      R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
```

---

## Internationalisation

Le site doit supporter **3 langues minimum** dès le départ :
- `/fr/` — Français (marché principal)
- `/en/` — Anglais (UK + US + international)
- `/de/` — Allemand (3e marché e-commerce européen)

Utilise `next-intl` pour la gestion i18n. Chaque page génère ses propres métadonnées SEO localisées. Les liens affiliés sont sélectionnés dynamiquement selon la locale du visiteur (Amazon FR pour `/fr/`, Amazon DE pour `/de/`, etc.).

---

## SEO — Points critiques

1. **Titres** : `Top {N} meilleurs {catégorie} {année} – Comparatif complet & Avis`
2. **Meta description** : 155 chars, inclut prix et nombre de produits testés
3. **Schema.org** : `ItemList` pour les comparatifs, `Product` + `AggregateRating` pour chaque produit, `FAQPage` pour la FAQ
4. **Core Web Vitals** : Images Next.js `<Image>` + lazy loading + R2 CDN
5. **Freshness** : `last_updated` visible sur chaque page + ISR revalidation quotidienne
6. **Disclosure** : Bandeau affilié légal en haut de chaque page (obligatoire RGPD)

---

## Règles de développement

### À chaque nouvelle feature :
1. **Schéma d'abord** : Toujours mettre à jour `supabase/migrations/` avant le code
2. **Types TypeScript** : Générer les types depuis Supabase (`npx supabase gen types`)
3. **SSG/ISR** : Toutes les pages comparatif en `generateStaticParams` + `revalidate: 86400`
4. **Variables d'env** : Jamais de credentials hardcodés — toujours `.env.local` ou GitHub Secrets
5. **Liens affiliés** : Toujours passer par `lib/affiliate-links.ts`, jamais directs dans les composants

### Priorité de développement (ordre strict) :
1. Schéma Supabase + seed données de test
2. Page comparatif individuelle (conversion)
3. Homepage + grille catégories
4. Scripts Python (génération images + publication Pinterest)
5. GitHub Actions workflows
6. SEO (sitemap, schema.org, métadonnées)
7. Internationalisation (en/de)
8. Dashboard analytics (optionnel, phase 2)

---

## Checklist avant chaque déploiement Vercel

- [ ] Variables d'environnement configurées dans Vercel Dashboard
- [ ] Supabase Row Level Security activé
- [ ] Bucket R2 en lecture publique (policy configurée)
- [ ] Disclosure affilié visible sur toutes les pages
- [ ] Sitemap accessible sur `/sitemap.xml`
- [ ] Core Web Vitals : LCP < 2.5s, CLS < 0.1
- [ ] Liens affiliés testés et fonctionnels (1 par partenaire)
- [ ] GitHub Secrets configurés pour tous les workflows Actions

---

## Troubleshooting fréquent

**R2 images 403** → Vérifier la public bucket policy dans Cloudflare dashboard  
**Supabase RLS bloque** → Utiliser `service_role_key` dans les scripts Python, `anon_key` côté client  
**Pinterest API 429** → Rate limit : max 100 pins/jour, espacer les appels de 30s  
**HF Inference timeout** → Modèles gratuits ont une file d'attente, implémenter retry avec backoff exponentiel  
**Vercel ISR stale** → POST vers `/api/revalidate` avec `REVALIDATE_SECRET` depuis les scripts Python après mise à jour Supabase  
**GitHub Actions coût** → Vérifier que les crons ne tournent QUE sur la branche `main`, utiliser `workflow_dispatch` pour les tests  
**`process` non défini TS** → `@types/node` est dans devDependencies mais `npm install` n'a pas encore été lancé  
**`Inter` import manquant** → Toujours importer `{ Inter } from "next/font/google"` explicitement dans layout.tsx  
**globals.css path** → Le fichier est à `app/globals.css` ; le layout `[locale]` l'importe avec `"../globals.css"`  
**`createServiceClient` absent** → `lib/supabase.ts` exporte `createServiceClient()` (service role) — ne jamais exposer côté client

---

## État du projet (session 3)

### ✅ Complété
- `supabase/migrations/001_initial_schema.sql` — 6 tables, RLS, paapi_enabled
- `scripts/seed.py` — 2 catégories (aspirateurs, lampes), 6 produits avec ASINs réels
- `scripts/update-amazon-prices-manual.py` — CLI coloré mise à jour hebdo manuelle
- `scripts/scrape_prices.py` — Scraping async 7 sites, proxy rotation, ScrapingBee fallback
- `scripts/generate-pinterest-image.py` — HF FLUX + Pillow overlay 1000×1500px
- `scripts/publish-pinterest.py` — Pinterest API v5, rate limiting, 100 pins/jour max
- `scripts/import-awin-feed.py` — Fnac/Darty/Boulanger/La Redoute/Maison du Monde (CSV feed Awin)
- `scripts/generate-content.py` — Ollama local + HF fallback, intro/guide/faq, ISR revalid.
- `scripts/upload-image.py` — Upload R2 CLI avec clé auto ou manuelle
- `lib/r2.ts` — S3-compatible client R2 (@aws-sdk/client-s3)
- `lib/supabase.ts` — exports: `supabase`, `createSupabaseServerClient()`, `createServiceClient()`
- `app/api/revalidate/route.ts` — POST protégé par REVALIDATE_SECRET
- `app/api/cron/update-prices/route.ts` — Vercel cron 5h UTC
- `.github/workflows/publish-pinterest.yml` — cron 8h/14h/20h UTC
- `.github/workflows/update-awin-feeds.yml` — cron 4h UTC
- `.github/workflows/update-prices.yml` — cron 5h UTC
- `middleware.ts` — next-intl routing fr/en/de
- `vercel.json` — CDN headers, crons, region cdg1
- `requirements.txt` — toutes les dépendances Python

### 🔑 Stratégie affiliés
- **Amazon FR** : liens manuels `https://www.amazon.fr/dp/{ASIN}?tag={AMAZON_TAG}` jusqu'à 3 ventes
- **PA-API** : débloquée après 3 ventes — `paapi_enabled = true` dans affiliate_links
- **Awin** : AWIN_API_TOKEN + AWIN_PUBLISHER_ID suffisent, scripts ready → juste remplir .env
- **Merchants Awin** : fnac (19024), darty (12188), boulanger (16285), la-redoute (12181), maison-du-monde (15697)

### 📋 À faire (phase 2)
- [ ] `npm install` + `next build` (vérifier 0 erreur)
- [ ] Remplir `.env.local` avec les vraies credentials
- [ ] `python scripts/seed.py` → vérifier ASINs sur amazon.fr avant
- [ ] Déployer sur Vercel → configurer tous les Secrets GitHub
- [ ] Activer R2 public bucket policy
- [ ] Configurer Pinterest board_id
- [ ] Ajouter catégories : robots aspirateurs, cafetières à grains (phase 2)
