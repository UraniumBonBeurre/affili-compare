-- ============================================================================
-- Migration : fix_pinterest_pins_schema
-- Date      : 2026-03-12
--
-- Ajoute les colonnes manquantes à pinterest_pins
-- (schéma initial 001 pas entièrement appliqué)
-- ============================================================================

ALTER TABLE pinterest_pins ADD COLUMN IF NOT EXISTS board_id       TEXT;
ALTER TABLE pinterest_pins ADD COLUMN IF NOT EXISTS description    TEXT;
ALTER TABLE pinterest_pins ADD COLUMN IF NOT EXISTS pin_url        TEXT;
ALTER TABLE pinterest_pins ADD COLUMN IF NOT EXISTS background_text TEXT;
ALTER TABLE pinterest_pins ADD COLUMN IF NOT EXISTS link_to_article TEXT;
ALTER TABLE pinterest_pins ADD COLUMN IF NOT EXISTS status         TEXT DEFAULT 'published';
ALTER TABLE pinterest_pins ADD COLUMN IF NOT EXISTS published_at   TIMESTAMPTZ;

-- Notifie PostgREST de recharger son cache schéma
NOTIFY pgrst, 'reload schema';
