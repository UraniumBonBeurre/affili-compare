-- ============================================================================
-- Migration : lifestyle_articles
-- Date      : 2026-03-10
--
-- Table stockant les articles "Top N incontournables pour [espace]" générés
-- automatiquement. Un article = 5 produits DIVERSIFIÉS pour un univers de vie
-- (chambre, salon, bureau, extérieur…), guidés par les tendances Pinterest.
--
-- Différence avec top5_articles :
--   top5_articles   → compare des produits du MÊME type (5 souris, 5 TV…)
--   lifestyle_articles → présente des produits DIFFÉRENTS pour un MÊME espace
--
-- Généré par : scripts/generate-lifestyle-article.py
-- A appliquer dans : Supabase > SQL Editor
-- ============================================================================

CREATE TABLE IF NOT EXISTS lifestyle_articles (
  id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  slug               text        UNIQUE NOT NULL,         -- "bedroom-essentials-2026-03"
  niche              text        NOT NULL,                -- "bedroom_essentials"
  niche_label_fr     text        NOT NULL,                -- "votre chambre"
  title_fr           text        NOT NULL,                -- "Top 5 incontournables pour votre chambre en mars 2026"
  intro_fr           text,                                -- Intro 120-200 mots
  products           jsonb       NOT NULL DEFAULT '[]',   -- [{id, name, brand, price, url, image_url, blurb_fr, category}]
  trending_keywords  jsonb       NOT NULL DEFAULT '[]',   -- Pinterest keywords ayant influencé la sélection
  month              char(7)     NOT NULL,                -- "2026-03"
  pin_images         jsonb       NOT NULL DEFAULT '[]',   -- ["/output/lifestyle_pins/xxx_hero.jpg", …]
  is_published       boolean     NOT NULL DEFAULT true,
  generated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (niche, month)                                   -- 1 article par niche par mois
);

-- Index chronologique (homepage / feeds)
CREATE INDEX IF NOT EXISTS lifestyle_articles_published_idx
  ON lifestyle_articles (is_published, generated_at DESC);

-- Index par niche (pour les pages de catégorie)
CREATE INDEX IF NOT EXISTS lifestyle_articles_niche_idx
  ON lifestyle_articles (niche, is_published);

-- Index sur le mois (pour les archives)
CREATE INDEX IF NOT EXISTS lifestyle_articles_month_idx
  ON lifestyle_articles (month DESC);

-- Row Level Security
ALTER TABLE lifestyle_articles ENABLE ROW LEVEL SECURITY;

-- Lecture publique des articles publiés
CREATE POLICY "lifestyle public read"
  ON lifestyle_articles FOR SELECT
  USING (is_published = true);

-- Écriture réservée au service role (scripts Python)
-- (pas de policy INSERT/UPDATE/DELETE → seul le service role peut écrire)

COMMENT ON TABLE lifestyle_articles IS
  'Articles "Top N incontournables pour [espace de vie]" — produits diversifiés '
  'guidés par les tendances Pinterest. Générés par generate-lifestyle-article.py.';

COMMENT ON COLUMN lifestyle_articles.products IS
  'JSONB array : [{id, name, brand, price, url, image_url, blurb_fr, category, rating}]';

COMMENT ON COLUMN lifestyle_articles.trending_keywords IS
  'Keywords Pinterest (growing/accelerating) ayant boosté la sélection de niche.';

COMMENT ON COLUMN lifestyle_articles.pin_images IS
  'Chemins locaux (output/lifestyle_pins/) des visuels Pinterest générés : hero, spotlight, checklist.';
