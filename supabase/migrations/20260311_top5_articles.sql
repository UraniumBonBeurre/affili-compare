-- ============================================================================
-- Migration : top5_articles
-- Date      : 2026-03-09
--
-- Table stockant les articles "Top 5 du mois" générés automatiquement.
-- Un article = top 5 produits pour une sous-catégorie + mois donnés.
-- Généré quotidiennement par scripts/generate-top5.py.
--
-- A appliquer dans : Supabase SQL Editor
-- ============================================================================

CREATE TABLE IF NOT EXISTS top5_articles (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  slug          text        UNIQUE NOT NULL,          -- "meilleures-souris-gaming-2026-03"
  category_slug text        NOT NULL,                 -- "gaming"
  subcategory   text        NOT NULL,                 -- "Souris gaming"
  keyword       text        NOT NULL,                 -- terme de recherche: "souris gaming"
  title_fr      text        NOT NULL,
  intro_fr      text,
  products      jsonb       NOT NULL DEFAULT '[]',    -- [{id,name,brand,price,url,blurb_fr}]
  month         char(7)     NOT NULL,                 -- "2026-03"
  is_published  boolean     NOT NULL DEFAULT true,
  generated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (keyword, month)
);

-- Accélère les requêtes homepage (ORDER BY generated_at DESC)
CREATE INDEX IF NOT EXISTS top5_articles_published_idx
  ON top5_articles (is_published, generated_at DESC);

-- Accélère les filtres par catégorie
CREATE INDEX IF NOT EXISTS top5_articles_category_idx
  ON top5_articles (category_slug, is_published);

-- Active le Row Level Security (lecture publique, écriture service-role only)
ALTER TABLE top5_articles ENABLE ROW LEVEL SECURITY;

-- Lecture publique des articles publiés
CREATE POLICY "top5 public read"
  ON top5_articles FOR SELECT
  USING (is_published = true);
