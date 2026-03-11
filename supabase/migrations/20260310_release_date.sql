-- Migration: ajoute release_date aux produits
ALTER TABLE products
  ADD COLUMN IF NOT EXISTS release_date date;

COMMENT ON COLUMN products.release_date IS 'Date de sortie du produit (mois+année suffisent, jour non significatif)';
