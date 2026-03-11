-- Ajoute la colonne embedding_text pour stocker le texte source de l'embedding
-- Permet de inspecter/débugger la qualité du texte utilisé pour la vectorisation

ALTER TABLE products
  ADD COLUMN IF NOT EXISTS embedding_text TEXT;
