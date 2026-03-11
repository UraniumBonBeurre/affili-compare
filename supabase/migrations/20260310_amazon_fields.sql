-- Migration: add EAN + Amazon affiliate columns to products
-- Apply via Supabase SQL Editor

ALTER TABLE products
  ADD COLUMN IF NOT EXISTS ean           text,
  ADD COLUMN IF NOT EXISTS amazon_asin   text,
  ADD COLUMN IF NOT EXISTS amazon_url    text;

-- Index for EAN lookups (enrichment script scans by ean)
CREATE INDEX IF NOT EXISTS products_ean_idx
  ON products (ean)
  WHERE ean IS NOT NULL;

-- Index for ASIN lookups (avoid re-querying already enriched products)
CREATE INDEX IF NOT EXISTS products_amazon_asin_idx
  ON products (amazon_asin)
  WHERE amazon_asin IS NOT NULL;
