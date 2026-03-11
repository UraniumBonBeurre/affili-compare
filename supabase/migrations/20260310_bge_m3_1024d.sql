-- Migration : passage de intfloat/multilingual-e5-small (384d) à BAAI/bge-m3 (1024d)
-- Les embeddings existants doivent être recalculés après cette migration.

-- 1. Supprimer l'index HNSW s'il existe (lié à la dimension)
DROP INDEX IF EXISTS products_embedding_hnsw;

-- 2. Redimensionner la colonne embedding : 384 → 1024
--    USING NULL réinitialise toutes les valeurs (recalcul obligatoire)
ALTER TABLE products
  ALTER COLUMN embedding TYPE vector(1024) USING NULL;

-- 3. Recréer l'index HNSW pour 1024 dims (après remplissage des embeddings)
-- CREATE INDEX CONCURRENTLY products_embedding_hnsw
--   ON products USING hnsw (embedding vector_cosine_ops)
--   WITH (m = 16, ef_construction = 64);

-- 4. Mettre à jour la fonction search_products_hybrid pour vector(1024)
DROP FUNCTION IF EXISTS search_products_hybrid(vector, text, integer, text, text);

CREATE FUNCTION search_products_hybrid(
  query_embedding  vector(1024),
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
  affiliate_url  text,
  price          numeric,
  currency       text,
  in_stock       boolean,
  merchant_key   text,
  hybrid_score   float,
  in_lexical     boolean
)
LANGUAGE plpgsql STABLE SECURITY DEFINER
AS $$
DECLARE
  ts_query tsquery;
BEGIN
  IF length(trim(query_text)) > 0 THEN
    SELECT to_tsquery('simple',
        string_agg(lower(word), ' | ' ORDER BY word)
      ) INTO ts_query
    FROM unnest(string_to_array(trim(query_text), ' ')) AS word
    WHERE length(trim(word)) > 1;
  END IF;

  RETURN QUERY
  WITH semantic AS (
    SELECT
      p.id                                                            AS pid,
      row_number() OVER (ORDER BY p.embedding <=> query_embedding)   AS rank_ix
    FROM products p
    WHERE p.embedding IS NOT NULL
      AND (p.active = true OR p.active IS NULL)
      AND (brand_filter    IS NULL OR p.brand         ILIKE '%' || brand_filter    || '%')
      AND (category_filter IS NULL OR p.category_slug ILIKE '%' || category_filter || '%')
    ORDER BY p.embedding <=> query_embedding
    LIMIT match_count * 4
  ),
  lexical AS (
    SELECT
      p.id AS pid,
      row_number() OVER (ORDER BY ts_rank_cd(p.fts, ts_query) DESC) AS rank_ix
    FROM products p
    WHERE ts_query IS NOT NULL
      AND p.fts @@ ts_query
      AND (p.active = true OR p.active IS NULL)
      AND (brand_filter    IS NULL OR p.brand         ILIKE '%' || brand_filter    || '%')
      AND (category_filter IS NULL OR p.category_slug ILIKE '%' || category_filter || '%')
    LIMIT match_count * 4
  ),
  rrf AS (
    SELECT
      COALESCE(s.pid, l.pid)                                   AS pid,
      COALESCE(1.0 / (60.0 + s.rank_ix), 0.0)
      + COALESCE(1.0 / (60.0 + l.rank_ix), 0.0)               AS rrf_score,
      (l.pid IS NOT NULL)                                      AS in_lexical
    FROM semantic s
    FULL OUTER JOIN lexical l ON l.pid = s.pid
  )
  SELECT
    p.id,
    p.name,
    p.brand,
    p.image_url,
    p.rating,
    p.review_count,
    p.category_slug,
    p.affiliate_url,
    p.price,
    p.currency,
    p.in_stock,
    p.merchant_key,
    r.rrf_score::float AS hybrid_score,
    r.in_lexical
  FROM rrf r
  JOIN products p ON p.id = r.pid
  ORDER BY r.rrf_score DESC
  LIMIT match_count;
END;
$$;

COMMENT ON FUNCTION search_products_hybrid IS
  'Recherche hybride RRF (sémantique HNSW + lexical GIN). Modèle: BAAI/bge-m3 (1024d). '
  'Filtre active=true. Retourne affiliate_url/price/currency/in_stock/merchant_key.';
