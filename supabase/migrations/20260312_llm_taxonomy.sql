-- ============================================================================
-- Migration : Classification LLM des produits
-- Date      : 2026-03-12
--
-- Objectif :
--   Ajouter des colonnes de classification sémantique remplies par LLM via
--   scripts/classify-products.py. Permet des requêtes directes par niche
--   au lieu du ILIKE fragile sur name/description.
--
-- Nouvelles colonnes :
--   llm_product_type   TEXT        — type précis du produit (ex: "camera_surveillance")
--   llm_room           TEXT        — pièce principale d'usage (ex: "entree")
--   llm_use_category   TEXT        — catégorie fonctionnelle (ex: "securite")
--   llm_niches         TEXT[]      — niches lifestyle compatibles (ex: ["entryway_decor","smart_home"])
--   llm_classified_at  TIMESTAMPTZ — horodatage de la dernière classification
--
-- Usage :
--   SELECT * FROM products WHERE llm_niches @> ARRAY['gaming_setup']
--   API REST PostgREST : llm_niches=cs.{gaming_setup}
-- ============================================================================

-- ── Nouvelles colonnes ────────────────────────────────────────────────────────

ALTER TABLE products
  ADD COLUMN IF NOT EXISTS llm_product_type  TEXT,
  ADD COLUMN IF NOT EXISTS llm_room          TEXT,
  ADD COLUMN IF NOT EXISTS llm_use_category  TEXT,
  ADD COLUMN IF NOT EXISTS llm_niches        TEXT[],
  ADD COLUMN IF NOT EXISTS llm_classified_at TIMESTAMPTZ;

-- ── Index ─────────────────────────────────────────────────────────────────────

-- Index GIN sur llm_niches — rend le filtre cs.{niche} ultra-rapide
CREATE INDEX IF NOT EXISTS products_llm_niches_gin
  ON products USING GIN (llm_niches);

-- Index B-tree sur les colonnes scalaires (filtres simples, ORDER BY)
CREATE INDEX IF NOT EXISTS products_llm_product_type_idx  ON products (llm_product_type);
CREATE INDEX IF NOT EXISTS products_llm_room_idx          ON products (llm_room);
CREATE INDEX IF NOT EXISTS products_llm_use_category_idx  ON products (llm_use_category);

-- Index pour récupérer rapidement les produits non encore classifiés
CREATE INDEX IF NOT EXISTS products_llm_unclassified_idx
  ON products (id)
  WHERE llm_classified_at IS NULL AND active = true;
