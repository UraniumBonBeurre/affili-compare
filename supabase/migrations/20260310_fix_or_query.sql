-- Migration : fix RPC (& → | dans tsquery) + ajout release_date
--
-- CAUSE DU BUG "camera ne renvoit rien" :
--   parseQuery("camera") → sqlKeywords = ["camera", "appareil", "webcam"]  (synonymes)
--   RPC reçoit query_text = "camera appareil webcam"
--   Avec & (AND) : to_tsquery('simple', 'appareil:* & camera:* & webcam:*')
--   → exige que les 3 mots coexistent dans le même produit → 0 résultats
--
-- FIX : utiliser | (OR) + :* (prefix) :
--   → produit matche si AU MOINS UN mot est présent  (recall élevé)
--   → "camera:*" matche "camera" ET "cameras"  (fix singulier/pluriel)
--   → RRF booste naturellement les produits qui matchent le plus de tokens

-- ── 1. Ajout release_date si pas encore présente ──────────────────────────────
ALTER TABLE products
  ADD COLUMN IF NOT EXISTS release_date date;

COMMENT ON COLUMN products.release_date IS
  'Date de sortie / disponibilité produit (source : valid_from du flux AWIN)';

-- ── 2. Mise à jour search_products_hybrid : & → | ────────────────────────────
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
  -- tsquery avec prefix matching (:*) et OR (|)
  -- |  (OR)     : boost si N'IMPORTE QUEL mot est présent (permissif + bonne recall)
  -- :* (prefix) : "camera:*" matche "camera" ET "cameras" (corrige singulier/pluriel)
  --
  -- NB : query_text contient les sqlKeywords déjà développés par parseQuery (ex: synonymes)
  --      → "camera" → "camera appareil webcam" → camera:* | appareil:* | webcam:*
  --      Avant (& AND) : les 3 mots devaient TOUS être présents → 0 résultat
  --      Après (| OR)  : au moins 1 mot suffit → results corrects
  IF length(trim(query_text)) > 0 THEN
    SELECT to_tsquery('simple',
        string_agg(lower(word) || ':*', ' | ')
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
  'Lexical: prefix :* + OR | → camera:* matche camera et cameras. '
  'FTS inclut description. active=true. release_date disponible.';
