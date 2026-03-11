-- Migration : ajout colonne description + FTS fix (camera ↔ cameras) + description dans FTS
--
-- Problème résolu : avec config 'simple', "camera" et "cameras" sont des lexèmes distincts.
-- → La recherche "camera" ne trouvait pas les produits Imou qui utilisent "cameras".
--
-- Solution :
--   1. Ajouter colonne description TEXT
--   2. Rebuild fts GENERATED pour inclure la description
--   3. Mettre à jour search_products_hybrid :
--      tsquery utilise désormais `:*` (prefix) + `&` (AND)
--      → "camera:*" matche "camera" ET "cameras" dans la même colonne

-- ── 1. Colonne description ────────────────────────────────────────────────────
ALTER TABLE products
  ADD COLUMN IF NOT EXISTS description TEXT;

COMMENT ON COLUMN products.description IS
  'Description courte du produit extraite du flux marchand (max 2000 chars)';

-- ── 2. Rebuild colonne fts avec description ───────────────────────────────────
-- La colonne est GENERATED ALWAYS AS, on doit la drop + re-créer pour la modifier.
ALTER TABLE products DROP COLUMN IF EXISTS fts;

ALTER TABLE products
  ADD COLUMN fts TSVECTOR
  GENERATED ALWAYS AS (
    to_tsvector('simple',
      coalesce(name, '')              || ' ' ||
      coalesce(brand, '')             || ' ' ||
      coalesce(merchant_category, '') || ' ' ||
      coalesce(category_slug, '')     || ' ' ||
      coalesce(description, '')
    )
  ) STORED;

DROP INDEX IF EXISTS products_fts_gin;
CREATE INDEX products_fts_gin ON products USING gin(fts);

-- ── 3. Mettre à jour search_products_hybrid ───────────────────────────────────
-- Changement de la branche lexicale :
--   • string_agg utilise `word:*` (prefix match) au lieu de `word` exact
--   • opérateur `&` (AND) au lieu de `|` (OR) → tous les mots doivent être présents
--   • "camera:*" → matche lexèmes "camera" ET "cameras" → plus de divergence singulier/pluriel

DROP FUNCTION IF EXISTS search_products_hybrid(vector(1024), text, integer, text, text);

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
  -- Construire la tsquery avec prefix matching (:*) et AND (&)
  -- "camera"   → camera:*   → matche "camera" et "cameras"
  -- "caméras de surveillance" → camera:* & de:* & surveil:*  (mots courts filtrés)
  IF length(trim(query_text)) > 0 THEN
    SELECT to_tsquery('simple',
        string_agg(lower(word) || ':*', ' & ')
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
  'Lexical: prefix matching :* + AND. Fixes camera≠cameras. '
  'FTS inclut description. Filtre active=true.';
