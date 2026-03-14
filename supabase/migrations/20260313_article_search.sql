-- ============================================================================
-- Migration : Article search — FTS + ids_products_used index
-- Date      : 2026-03-13  (v2 — remplace la version qui a échoué)
--
-- Suit exactement le même pattern que products.fts (GENERATED ALWAYS AS STORED).
-- Pas de trigger, pas de table séparée : ids_products_used uuid[] existe déjà.
--
-- Deux ajouts :
--   A. Colonne fts tsvector GENERATED (titre + sous-catégorie + intro + body)
--      → GIN index → requête O(log n) même à >10k articles
--   B. Index GIN sur ids_products_used
--      → lookup O(log n) "quels articles contiennent ces produits ?"
--
-- À exécuter dans : Supabase SQL Editor (une seule fois)
-- ============================================================================

-- ── A. Colonne FTS sur top_articles ─────────────────────────────────────────
--
-- Poids A : titre + sous-catégorie (les plus importants)
-- Poids B : intro fr et en
-- Poids C : corps de l'article tr/en (tags HTML retirés par regexp)
--
-- Tout est IMMUTABLE → compatible GENERATED ALWAYS AS STORED.

ALTER TABLE top_articles
  ADD COLUMN IF NOT EXISTS fts tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', coalesce(title, '')),                                         'A') ||
    setweight(to_tsvector('simple', coalesce(content->>'subcategory',    '')),                    'A') ||
    setweight(to_tsvector('simple', coalesce(content->>'subcategory_en', '')),                    'A') ||
    setweight(to_tsvector('simple', regexp_replace(coalesce(content->>'intro_fr',      ''), '<[^>]+>', ' ', 'g')), 'B') ||
    setweight(to_tsvector('simple', regexp_replace(coalesce(content->>'intro_en',      ''), '<[^>]+>', ' ', 'g')), 'B') ||
    setweight(to_tsvector('simple', regexp_replace(coalesce(content->>'body_html_fr',  ''), '<[^>]+>', ' ', 'g')), 'C') ||
    setweight(to_tsvector('simple', regexp_replace(coalesce(content->>'body_html_en',  ''), '<[^>]+>', ' ', 'g')), 'C')
  ) STORED;

-- Index GIN pour la recherche plein-texte (O(log n))
CREATE INDEX IF NOT EXISTS top_articles_fts_gin
  ON top_articles USING gin(fts);


-- ── B. Index GIN sur ids_products_used ──────────────────────────────────────
--
-- Permet de répondre efficacement à "quels articles utilisent ces product_ids ?"
-- via l'opérateur && (array overlap) — colonne déjà présente dans bootstrap.sql.

CREATE INDEX IF NOT EXISTS top_articles_products_gin
  ON top_articles USING gin(ids_products_used);
