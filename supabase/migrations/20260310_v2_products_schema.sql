-- ============================================================================
-- Migration v2 : Nouvelle architecture table products
-- Date      : 2026-03-10
--
-- Objectifs :
--   1. Colonne generated `fts` STORED (pgvector + merchant_category)
--   2. Prix / stock / lien affilié directement sur le produit (imports batch)
--   3. merchant_key pour identifier la source de chaque produit
--   4. Soft-delete via `active` (UPDATE au lieu de DELETE lors des mises à jour)
--   5. Index unique composite (external_id, merchant_key) → batch upsert possible
--   6. Mise à jour de search_products_hybrid : filtre active=true + retourne
--      affiliate_url, price, currency, in_stock, merchant_key
--
-- ⚠ Appliquer APRÈS les migrations précédentes
-- ⚠ Requiert extension vector (déjà installée via 20260309_vector_search.sql)
-- ============================================================================

-- ── 1. Supprimer les colonnes générées AVANT de toucher leurs dépendances ─────

-- fts dépend de rich_text → on le drop d'abord
ALTER TABLE products DROP COLUMN IF EXISTS fts;

-- rich_text remplacée par merchant_category (stocké brut, plus structuré)
ALTER TABLE products DROP COLUMN IF EXISTS rich_text;

-- ── 2. Nouvelles colonnes opérationnelles ─────────────────────────────────────

ALTER TABLE products
  -- Source du produit
  ADD COLUMN IF NOT EXISTS merchant_key      TEXT,              -- "rue-du-commerce", "imou_fr"
  ADD COLUMN IF NOT EXISTS merchant_name     TEXT,              -- "Rue du Commerce"

  -- Prix & stock mis à jour à chaque sync
  ADD COLUMN IF NOT EXISTS price             NUMERIC(12,2),
  ADD COLUMN IF NOT EXISTS currency          TEXT DEFAULT 'EUR',
  ADD COLUMN IF NOT EXISTS in_stock          BOOLEAN DEFAULT true,

  -- Lien affilié direct (évite de requêter affiliate_links pour les imports bulk)
  ADD COLUMN IF NOT EXISTS affiliate_url     TEXT,

  -- Catégorisation brute (alimente le FTS)
  ADD COLUMN IF NOT EXISTS merchant_category TEXT,

  -- Identifiants supplémentaires
  ADD COLUMN IF NOT EXISTS mpn               TEXT,

  -- Cycle de vie
  ADD COLUMN IF NOT EXISTS active            BOOLEAN DEFAULT true,
  ADD COLUMN IF NOT EXISTS last_price_update TIMESTAMPTZ;

-- ── 3. Contrainte unique composite pour les upserts batch ──────────────────

-- Supprimer l'ancien index partiel sur external_id seul
DROP INDEX IF EXISTS products_external_id_idx;

-- Nouvel index composite : même produit + même marchand = même ligne
-- (NULL != NULL en Postgres → pas de collision sur les produits sans external_id)
CREATE UNIQUE INDEX IF NOT EXISTS products_external_merchant_uq
  ON products (external_id, merchant_key);

-- ── 4. Index de support ───────────────────────────────────────────────────────

-- Requêtes "donne-moi tous les produits du marchand X" (cmd_update)
CREATE INDEX IF NOT EXISTS products_merchant_key_idx
  ON products (merchant_key)
  WHERE merchant_key IS NOT NULL;

-- Filtre active=true fréquent dans la recherche
CREATE INDEX IF NOT EXISTS products_active_slug_idx
  ON products (category_slug, active)
  WHERE active = true;

-- ── 5. Colonne FTS générée (remplace rich_text) ───────────────────────────────
-- Combinaison : nom + marque + catégorie marchande + slug catégorie
-- Modèle 'simple' : preserve les codes-modèles exacts (ex: "GTX 4090", "A34")

ALTER TABLE products
  ADD COLUMN fts TSVECTOR
  GENERATED ALWAYS AS (
    to_tsvector('simple',
      coalesce(name, '')              || ' ' ||
      coalesce(brand, '')             || ' ' ||
      coalesce(merchant_category, '') || ' ' ||
      coalesce(category_slug, '')
    )
  ) STORED;

DROP INDEX IF EXISTS products_fts_gin;
CREATE INDEX products_fts_gin ON products USING gin(fts);

-- ── 6. Mise à jour de search_products_hybrid ─────────────────────────────────
-- Changements :
--   • Filtre (active = true OR active IS NULL) sur les deux branches
--   • RETURNS TABLE étendu : affiliate_url, price, currency, in_stock, merchant_key

DROP FUNCTION IF EXISTS search_products_hybrid(vector, text, integer, text, text);

CREATE FUNCTION search_products_hybrid(
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
  'Recherche hybride RRF (sémantique HNSW + lexical GIN). Filtre active=true. '
  'Retourne affiliate_url/price/currency/in_stock/merchant_key pour éviter une '
  'jointure affiliate_links sur les produits importés en bulk.';
