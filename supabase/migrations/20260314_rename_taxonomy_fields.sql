-- Renommer site_category → llm_category, site_niche → llm_niche
-- Ajouter llm_product_type + index pour le dashboard
ALTER TABLE products RENAME COLUMN site_category TO llm_category;
ALTER TABLE products RENAME COLUMN site_niche     TO llm_niche;
ALTER TABLE products ADD COLUMN IF NOT EXISTS llm_product_type TEXT;

CREATE INDEX IF NOT EXISTS idx_products_llm_category     ON products(llm_category);
CREATE INDEX IF NOT EXISTS idx_products_llm_niche        ON products(llm_niche);
CREATE INDEX IF NOT EXISTS idx_products_llm_product_type ON products(llm_product_type);
