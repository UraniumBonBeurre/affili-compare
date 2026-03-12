-- Drop unused columns from products table
-- These columns were never populated from real data sources.
ALTER TABLE products
  DROP COLUMN IF EXISTS image_r2_key,
  DROP COLUMN IF EXISTS rating,
  DROP COLUMN IF EXISTS review_count,
  DROP COLUMN IF EXISTS badge,
  DROP COLUMN IF EXISTS pros_fr,
  DROP COLUMN IF EXISTS cons_fr,
  DROP COLUMN IF EXISTS pros_en,
  DROP COLUMN IF EXISTS cons_en,
  DROP COLUMN IF EXISTS fts,
  DROP COLUMN IF EXISTS ean,
  DROP COLUMN IF EXISTS amazon_asin,
  DROP COLUMN IF EXISTS amazon_url,
  DROP COLUMN IF EXISTS mpn;
