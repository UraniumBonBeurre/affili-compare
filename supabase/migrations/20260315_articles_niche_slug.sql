-- Migration: add niche_slug and category_id to top_articles
-- Purpose: allow direct indexed filtering of articles by niche/category
--          instead of fragile content->>subcategory name matching.

ALTER TABLE top_articles
  ADD COLUMN IF NOT EXISTS niche_slug  text,
  ADD COLUMN IF NOT EXISTS category_id text;

CREATE INDEX IF NOT EXISTS idx_top_articles_niche_slug  ON top_articles(niche_slug);
CREATE INDEX IF NOT EXISTS idx_top_articles_category_id ON top_articles(category_id);

COMMENT ON COLUMN top_articles.niche_slug  IS 'Niche slug from config/taxonomy/categories.json, e.g. "gaming"';
COMMENT ON COLUMN top_articles.category_id IS 'Category id from config/taxonomy/categories.json, e.g. "tech-high-tech"';
