-- ============================================================================
-- Migration : refactoring v2 — top_articles + pinterest_pins update
-- Date      : 2026-07
--
-- 1. Crée la table top_articles (remplace top5_articles)
-- 2. Met à jour pinterest_pins (ajoute colonnes pour les articles)
-- ============================================================================

-- ══════════════════════════════════════════════════════════════════════════════
-- 1. TABLE top_articles (nouvelle table propre)
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS top_articles (
  id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  slug               text        UNIQUE NOT NULL,
  url                text,
  title              text        NOT NULL,
  ids_products_used  uuid[]      DEFAULT '{}',
  content            jsonb       NOT NULL DEFAULT '{}',
  pin_images         jsonb       DEFAULT '[]',
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS top_articles_created_idx
  ON top_articles (created_at DESC);

ALTER TABLE top_articles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "top_articles public read"
  ON top_articles FOR SELECT
  USING (true);

CREATE POLICY "top_articles service write"
  ON top_articles FOR ALL
  USING (auth.role() = 'service_role');

-- ══════════════════════════════════════════════════════════════════════════════
-- 2. UPDATE pinterest_pins — ajout colonnes pour les articles
-- ══════════════════════════════════════════════════════════════════════════════

-- URL du pin Pinterest
ALTER TABLE pinterest_pins ADD COLUMN IF NOT EXISTS pin_url text;

-- Texte de fond utilisé pour la génération d'image
ALTER TABLE pinterest_pins ADD COLUMN IF NOT EXISTS background_text text;

-- Lien vers l'article top_articles associé
ALTER TABLE pinterest_pins ADD COLUMN IF NOT EXISTS link_to_article text;

-- Status du pin (published, draft, error)
ALTER TABLE pinterest_pins ADD COLUMN IF NOT EXISTS status text DEFAULT 'published';

-- Index pour retrouver les pins par article
CREATE INDEX IF NOT EXISTS idx_pinterest_pins_link_article
  ON pinterest_pins (link_to_article);

CREATE INDEX IF NOT EXISTS idx_pinterest_pins_published
  ON pinterest_pins (published_at DESC);
