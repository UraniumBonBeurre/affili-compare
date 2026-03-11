-- Migration 002: Add subcategory to comparisons
-- Run in Supabase Dashboard > SQL Editor

ALTER TABLE comparisons
  ADD COLUMN IF NOT EXISTS subcategory TEXT;

COMMENT ON COLUMN comparisons.subcategory IS 'Sous-catégorie optionnelle pour grouper les comparatifs dans la page catégorie — ex: "Aspirateurs sans fil", "Robots aspirateurs"';
