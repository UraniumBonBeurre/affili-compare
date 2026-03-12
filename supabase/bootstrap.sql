-- ============================================================================
-- AffiliCompare — Bootstrap SQL (installation fraîche)
-- Crée les 3 tables du projet : products · pinterest_pins · top_articles
-- À coller dans : Supabase SQL Editor > Run
-- ============================================================================

-- Extensions requises
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ══════════════════════════════════════════════════════════════════════════════
-- 1. TABLE products
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS products (
  -- Identifiants
  id                 uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  external_id        text,                                     -- aw_product_id Awin
  mpn                text,                                     -- référence fabricant
  ean                text,

  -- Informations produit
  name               text          NOT NULL,
  brand              text          NOT NULL DEFAULT '',
  image_r2_key       text,
  image_url          text,
  category_slug      text,
  merchant_category  text,                                     -- catégorie brute du flux
  release_date       date,

  -- Source / marchand
  merchant_key       text,                                     -- "rue-du-commerce", "imou_fr"
  merchant_name      text,

  -- Prix & stock
  price              numeric(12,2),
  currency           text          DEFAULT 'EUR',
  in_stock           boolean       DEFAULT true,
  affiliate_url      text,
  amazon_asin        text,
  amazon_url         text,
  last_price_update  timestamptz,

  -- Évaluation manuelle
  rating             decimal(3,1)  CHECK (rating BETWEEN 0 AND 5),
  review_count       integer       DEFAULT 0,
  badge              text          CHECK (badge IN ('best-value', 'premium', 'budget', NULL)),

  -- Contenu éditorial (facultatif, héritage comparatifs)
  pros_fr            jsonb         DEFAULT '[]',
  cons_fr            jsonb         DEFAULT '[]',
  pros_en            jsonb         DEFAULT '[]',
  cons_en            jsonb         DEFAULT '[]',

  -- Classification LLM (remplie par classification.py)
  llm_product_type   text,
  llm_room           text,
  llm_use_category   text,
  llm_niches         text[],
  llm_classified_at  timestamptz,

  -- Embeddings (remplis par create_embeddings.py — BAAI/bge-m3 1024d)
  embedding          vector(1024),
  embedding_text     text,

  -- Full-text search généré
  fts                tsvector      GENERATED ALWAYS AS (
                       to_tsvector('simple',
                         coalesce(name, '')              || ' ' ||
                         coalesce(brand, '')             || ' ' ||
                         coalesce(merchant_category, '') || ' ' ||
                         coalesce(category_slug, '')
                       )
                     ) STORED,

  -- Cycle de vie
  active             boolean       DEFAULT true,
  created_at         timestamptz   NOT NULL DEFAULT now()
);

-- Index products
CREATE UNIQUE INDEX IF NOT EXISTS products_external_merchant_uq
  ON products (external_id, merchant_key);

CREATE INDEX IF NOT EXISTS products_fts_gin
  ON products USING gin(fts);

CREATE INDEX IF NOT EXISTS products_llm_niches_gin
  ON products USING gin(llm_niches);

CREATE INDEX IF NOT EXISTS products_embedding_hnsw
  ON products USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS products_merchant_key_idx
  ON products (merchant_key) WHERE merchant_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS products_active_idx
  ON products (category_slug, active) WHERE active = true;

CREATE INDEX IF NOT EXISTS products_llm_unclassified_idx
  ON products (id) WHERE llm_classified_at IS NULL AND active = true;

CREATE INDEX IF NOT EXISTS products_ean_idx
  ON products (ean) WHERE ean IS NOT NULL;

CREATE INDEX IF NOT EXISTS products_category_slug_idx
  ON products (category_slug) WHERE category_slug IS NOT NULL;

-- RLS products
ALTER TABLE products ENABLE ROW LEVEL SECURITY;

CREATE POLICY "products public read"
  ON products FOR SELECT USING (true);

CREATE POLICY "products service write"
  ON products FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- ══════════════════════════════════════════════════════════════════════════════
-- 2. TABLE top_articles
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS top_articles (
  id                 uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  slug               text          UNIQUE NOT NULL,           -- ex: "top-5-cameras-surveillance-2026-03"
  url                text,                                    -- URL publique sur le site
  title              text          NOT NULL,
  ids_products_used  uuid[]        DEFAULT '{}',              -- FK logique → products.id
  content            jsonb         NOT NULL DEFAULT '{}',     -- {intro, blurbs:[{product_id, text}]}
  pin_images         jsonb         DEFAULT '[]',              -- [{r2_key, url, type:"hero"|"spotlight"}]
  created_at         timestamptz   NOT NULL DEFAULT now()
);

-- Index top_articles
CREATE INDEX IF NOT EXISTS top_articles_created_idx
  ON top_articles (created_at DESC);

-- RLS top_articles
ALTER TABLE top_articles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "top_articles public read"
  ON top_articles FOR SELECT USING (true);

CREATE POLICY "top_articles service write"
  ON top_articles FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- ══════════════════════════════════════════════════════════════════════════════
-- 3. TABLE pinterest_pins
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS pinterest_pins (
  id               uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  pin_id           text,                                      -- ID retourné par l'API Pinterest
  image_r2_key     text,
  image_url        text,
  title            text,
  description      text,
  locale           text          DEFAULT 'fr',
  board_id         text,
  created_at       timestamptz   NOT NULL DEFAULT now()
);

-- Toutes les colonnes optionnelles via ADD COLUMN IF NOT EXISTS pour fonctionner
-- sur une table déjà existante (base en production) comme sur installation fraîche.
ALTER TABLE pinterest_pins
  ADD COLUMN IF NOT EXISTS published_at     timestamptz,
  ADD COLUMN IF NOT EXISTS impressions      integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS clicks           integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS saves            integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS pin_url          text,             -- URL du pin sur Pinterest
  ADD COLUMN IF NOT EXISTS background_text  text,             -- texte de fond utilisé à la génération
  ADD COLUMN IF NOT EXISTS link_to_article  text,             -- slug ou URL de top_articles associé
  ADD COLUMN IF NOT EXISTS status           text DEFAULT 'published'; -- published | draft | error

-- Index pinterest_pins
CREATE INDEX IF NOT EXISTS idx_pinterest_pins_link_article
  ON pinterest_pins (link_to_article);

CREATE INDEX IF NOT EXISTS idx_pinterest_pins_published
  ON pinterest_pins (published_at DESC);

-- RLS pinterest_pins
ALTER TABLE pinterest_pins ENABLE ROW LEVEL SECURITY;

CREATE POLICY "pinterest_pins public read"
  ON pinterest_pins FOR SELECT USING (true);

CREATE POLICY "pinterest_pins service write"
  ON pinterest_pins FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- ══════════════════════════════════════════════════════════════════════════════
-- 4. FONCTION de recherche hybride (RRF sémantique + lexical)
--    Utilisée par l'API Next.js via supabase.rpc('search_products_hybrid', ...)
-- ══════════════════════════════════════════════════════════════════════════════

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
      p.id AS pid,
      row_number() OVER (ORDER BY p.embedding <=> query_embedding) AS rank_ix
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
      COALESCE(s.pid, l.pid)                                 AS pid,
      COALESCE(1.0 / (60.0 + s.rank_ix), 0.0)
        + COALESCE(1.0 / (60.0 + l.rank_ix), 0.0)           AS rrf_score,
      (l.pid IS NOT NULL)                                    AS in_lexical
    FROM semantic s
    FULL OUTER JOIN lexical l ON l.pid = s.pid
  )
  SELECT
    p.id, p.name, p.brand, p.image_url, p.rating, p.review_count,
    p.category_slug, p.affiliate_url, p.price, p.currency,
    p.in_stock, p.merchant_key,
    r.rrf_score::float AS hybrid_score,
    r.in_lexical
  FROM rrf r
  JOIN products p ON p.id = r.pid
  ORDER BY r.rrf_score DESC
  LIMIT match_count;
END;
$$;
