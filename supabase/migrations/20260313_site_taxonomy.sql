-- Migration : ajout des colonnes site_category et site_niche sur les produits
-- Ces colonnes seront remplies par classification.py --only-site-taxonomy

ALTER TABLE products
  ADD COLUMN IF NOT EXISTS site_category TEXT,
  ADD COLUMN IF NOT EXISTS site_niche    TEXT;

CREATE INDEX IF NOT EXISTS idx_products_site_category ON products(site_category);
CREATE INDEX IF NOT EXISTS idx_products_site_niche    ON products(site_niche);

COMMENT ON COLUMN products.site_category IS 'Grande catégorie du site, ex: tech-high-tech (slug de config/site_categories.json)';
COMMENT ON COLUMN products.site_niche    IS 'Niche du site, ex: gaming (slug de config/site_categories.json)';
