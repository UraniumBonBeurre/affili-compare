-- ============================================================================
-- Migration : Recherche vectorielle hybride (pgvector)
-- Date      : 2026-03-09
-- Modèle    : paraphrase-multilingual-MiniLM-L12-v2 (384 dims)
--
-- À exécuter dans : Supabase SQL Editor (une seule fois)
-- ============================================================================

-- 1. Extension pgvector (gratuite dans Supabase)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Colonnes vector sur la table products
ALTER TABLE products
  ADD COLUMN IF NOT EXISTS embedding    vector(384),
  ADD COLUMN IF NOT EXISTS rich_text    text,
  ADD COLUMN IF NOT EXISTS category_slug text;

-- 3. Index HNSW pour la recherche ANN (Approximate Nearest Neighbor)
--    m=16 ef_construction=64 → bon équilibre précision/vitesse pour <100k produits
CREATE INDEX IF NOT EXISTS products_embedding_hnsw
  ON products USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- 4. Index GIN pour la recherche plein-texte en français (part hybride)
CREATE INDEX IF NOT EXISTS products_rich_text_fts
  ON products USING gin(to_tsvector('french', coalesce(rich_text, name, '')));

-- 5. Index sur category_slug (pour les filtres habituels)
CREATE INDEX IF NOT EXISTS products_category_slug_idx
  ON products (category_slug)
  WHERE category_slug IS NOT NULL;

-- ============================================================================
-- Fonction de recherche hybride : vector (70%) + BM25 keyword (30%)
-- Utilisée par l'API Next.js via supabase.rpc('search_products_hybrid', ...)
-- ============================================================================
CREATE OR REPLACE FUNCTION search_products_hybrid(
  query_embedding  vector(384),
  query_text       text    DEFAULT '',
  match_count      int     DEFAULT 15,
  brand_filter     text    DEFAULT NULL,
  category_filter  text    DEFAULT NULL
)
RETURNS TABLE (
  id             uuid,
  name           text,
  brand          text,
  image_url      text,
  rating         numeric,
  review_count   int,
  category_slug  text,
  hybrid_score   float
)
LANGUAGE plpgsql STABLE SECURITY DEFINER
AS $$
BEGIN
  RETURN QUERY
  WITH vector_results AS (
    -- Recherche par similarité cosinus
    SELECT
      p.id                                           AS pid,
      (1 - (p.embedding <=> query_embedding))::float AS vs
    FROM products p
    WHERE p.embedding IS NOT NULL
      AND (brand_filter    IS NULL OR p.brand         ILIKE '%' || brand_filter    || '%')
      AND (category_filter IS NULL OR p.category_slug ILIKE '%' || category_filter || '%')
    ORDER BY p.embedding <=> query_embedding
    LIMIT 60
  ),
  text_results AS (
    -- Recherche plein-texte française (BM25-like via ts_rank_cd)
    SELECT
      p.id AS pid,
      LEAST(
        ts_rank_cd(
          to_tsvector('french', coalesce(p.rich_text, p.name, '')),
          plainto_tsquery('french', query_text)
        ) * 20,        -- amplifier : ts_rank retourne des valeurs ~0.01–0.05
        1.0
      )::float AS ts
    FROM products p
    WHERE query_text <> ''
      AND (brand_filter    IS NULL OR p.brand         ILIKE '%' || brand_filter    || '%')
      AND (category_filter IS NULL OR p.category_slug ILIKE '%' || category_filter || '%')
      AND to_tsvector('french', coalesce(p.rich_text, p.name, ''))
          @@ plainto_tsquery('french', query_text)
    LIMIT 60
  ),
  combined AS (
    SELECT
      COALESCE(v.pid, t.pid) AS pid,
      COALESCE(v.vs, 0.0)    AS vs,
      COALESCE(t.ts, 0.0)    AS ts,
      -- Hybrid score : 70% sémantique + 30% lexical
      (COALESCE(v.vs, 0.0) * 0.7 + COALESCE(t.ts, 0.0) * 0.3) AS hs
    FROM vector_results v
    FULL OUTER JOIN text_results t USING (pid)
    ORDER BY hs DESC
    LIMIT match_count * 2
  )
  SELECT
    p.id,
    p.name,
    p.brand,
    p.image_url,
    p.rating,
    p.review_count,
    p.category_slug,
    c.hs::float AS hybrid_score
  FROM combined c
  JOIN products p ON p.id = c.pid
  ORDER BY c.hs DESC
  LIMIT match_count;
END;
$$;

-- ============================================================================
-- Fonction de recherche par vecteur seul (fallback simple)
-- ============================================================================
CREATE OR REPLACE FUNCTION match_products(
  query_embedding vector(384),
  match_count     int  DEFAULT 15,
  brand_filter    text DEFAULT NULL
)
RETURNS TABLE (
  id          uuid,
  name        text,
  brand       text,
  image_url   text,
  rating      numeric,
  similarity  float
)
LANGUAGE plpgsql STABLE SECURITY DEFINER
AS $$
BEGIN
  RETURN QUERY
  SELECT
    p.id,
    p.name,
    p.brand,
    p.image_url,
    p.rating,
    (1 - (p.embedding <=> query_embedding))::float AS similarity
  FROM products p
  WHERE p.embedding IS NOT NULL
    AND (brand_filter IS NULL OR p.brand ILIKE '%' || brand_filter || '%')
  ORDER BY p.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- ============================================================================
-- Commentaires (documentation inline dans la DB)
-- ============================================================================
COMMENT ON COLUMN products.embedding    IS 'Vecteur 384 dims — modèle paraphrase-multilingual-MiniLM-L12-v2';
COMMENT ON COLUMN products.rich_text    IS 'Texte riche pour l''embedding : "passage: {nom} {marque} {catégorie} {prix}€"';
COMMENT ON COLUMN products.category_slug IS 'Slug catégorie Supabase (dénormalisé pour perf)';
COMMENT ON FUNCTION search_products_hybrid IS 'Recherche hybride 70% vectorielle + 30% BM25. Params: query_embedding, query_text, match_count, brand_filter, category_filter';
