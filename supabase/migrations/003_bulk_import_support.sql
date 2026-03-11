-- ============================================================================
-- Migration 003 : Support du bulk import de flux Awin
-- Date : 2026-03-09
--
-- Ajoute :
--   - products.external_id  : identifiant unique côté partenaire (aw_product_id)
--   - Index unique partiel sur affiliate_links(product_id, partner)
--     quand comparison_id IS NULL (produits importés hors comparatif)
--
-- À exécuter dans Supabase SQL Editor (une seule fois, avant bulk-import-feed.py)
-- ============================================================================

-- 1. Colonne external_id sur products
--    Contiendra l'aw_product_id Awin ou tout autre identifiant partenaire.
ALTER TABLE products
  ADD COLUMN IF NOT EXISTS external_id TEXT;

-- 2. Index unique sur external_id (ignore les NULL → n'affecte pas les produits existants)
CREATE UNIQUE INDEX IF NOT EXISTS products_external_id_idx
  ON products (external_id)
  WHERE external_id IS NOT NULL;

-- 3. Index unique partiel sur affiliate_links pour les imports bulk (sans comparatif)
--    Permet l'upsert par (product_id, partner) quand comparison_id est NULL.
CREATE UNIQUE INDEX IF NOT EXISTS affiliate_links_product_partner_no_comp_idx
  ON affiliate_links (product_id, partner)
  WHERE comparison_id IS NULL;

-- ============================================================================
COMMENT ON COLUMN products.external_id IS 'Identifiant produit côté partenaire (aw_product_id Awin). NULL pour les produits créés manuellement.';
