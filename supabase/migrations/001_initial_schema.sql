-- ============================================================
-- AffiliCompare — Migration 001 : Schéma initial complet
-- ============================================================

-- Extension UUID (disponible par défaut dans Supabase)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- TABLE : categories
-- ============================================================
CREATE TABLE IF NOT EXISTS categories (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug                  TEXT UNIQUE NOT NULL,
  name_fr               TEXT NOT NULL,
  name_en               TEXT,
  name_de               TEXT,
  meta_description_fr   TEXT,
  meta_description_en   TEXT,
  meta_description_de   TEXT,
  pinterest_board_id    TEXT,
  icon                  TEXT,           -- emoji ou nom d'icône Lucide
  is_active             BOOLEAN DEFAULT true,
  display_order         INTEGER DEFAULT 0,
  created_at            TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- TABLE : comparisons
-- ============================================================
CREATE TABLE IF NOT EXISTS comparisons (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug                TEXT UNIQUE NOT NULL,
  category_id         UUID REFERENCES categories(id) ON DELETE SET NULL,
  title_fr            TEXT NOT NULL,
  title_en            TEXT,
  title_de            TEXT,
  intro_fr            TEXT,
  intro_en            TEXT,
  intro_de            TEXT,
  buying_guide_fr     TEXT,
  buying_guide_en     TEXT,
  buying_guide_de     TEXT,
  faq_fr              JSONB,            -- [{question, answer}]
  faq_en              JSONB,
  faq_de              JSONB,
  last_updated        TIMESTAMPTZ DEFAULT now(),
  is_published        BOOLEAN DEFAULT false,
  seo_score           INTEGER CHECK (seo_score BETWEEN 0 AND 100),
  monthly_views       INTEGER DEFAULT 0,
  created_at          TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- TABLE : products
-- ============================================================
CREATE TABLE IF NOT EXISTS products (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name            TEXT NOT NULL,
  brand           TEXT NOT NULL,
  image_r2_key    TEXT,
  image_url       TEXT,
  rating          DECIMAL(3,1) CHECK (rating BETWEEN 0 AND 5),
  review_count    INTEGER DEFAULT 0,
  badge           TEXT CHECK (badge IN ('best-value', 'premium', 'budget', NULL)),
  pros_fr         JSONB DEFAULT '[]'::JSONB,    -- ["Puissant", "Léger"]
  cons_fr         JSONB DEFAULT '[]'::JSONB,
  pros_en         JSONB DEFAULT '[]'::JSONB,
  cons_en         JSONB DEFAULT '[]'::JSONB,
  created_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- TABLE : comparison_products  (table de jointure ordonnée)
-- ============================================================
CREATE TABLE IF NOT EXISTS comparison_products (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  comparison_id   UUID NOT NULL REFERENCES comparisons(id) ON DELETE CASCADE,
  product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  position        INTEGER DEFAULT 0,    -- ordre d'affichage dans le tableau
  UNIQUE (comparison_id, product_id)
);

-- ============================================================
-- TABLE : affiliate_links
-- ============================================================
CREATE TABLE IF NOT EXISTS affiliate_links (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id        UUID REFERENCES products(id) ON DELETE CASCADE,
  comparison_id     UUID REFERENCES comparisons(id) ON DELETE CASCADE,
  partner           TEXT NOT NULL,       -- "amazon_fr", "cdiscount", "fnac", "ebay_de"
  country           TEXT NOT NULL,       -- "fr", "uk", "de", "us"
  url               TEXT NOT NULL,
  price             DECIMAL(10,2),
  currency          TEXT DEFAULT 'EUR',
  in_stock          BOOLEAN DEFAULT true,
  commission_rate   DECIMAL(5,2),        -- % commission estimé
  paapi_enabled     BOOLEAN DEFAULT false, -- true quand PA-API est activée (après 3 ventes)
  last_checked      TIMESTAMPTZ DEFAULT now(),
  created_at        TIMESTAMPTZ DEFAULT now(),
  CONSTRAINT valid_country  CHECK (country  IN ('fr', 'uk', 'de', 'us', 'be', 'ch', 'ca')),
  CONSTRAINT valid_currency CHECK (currency IN ('EUR', 'GBP', 'USD', 'CHF', 'CAD'))
);

-- ============================================================
-- TABLE : pinterest_pins
-- ============================================================
CREATE TABLE IF NOT EXISTS pinterest_pins (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  comparison_id   UUID REFERENCES comparisons(id) ON DELETE SET NULL,
  pin_id          TEXT,                  -- ID retourné par l'API Pinterest
  image_r2_key    TEXT,
  image_url       TEXT,
  title           TEXT,
  description     TEXT,
  locale          TEXT DEFAULT 'fr',
  board_id        TEXT,
  published_at    TIMESTAMPTZ,
  impressions     INTEGER DEFAULT 0,
  clicks          INTEGER DEFAULT 0,
  saves           INTEGER DEFAULT 0,
  created_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- INDEX pour les performances
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_comparisons_category     ON comparisons(category_id);
CREATE INDEX IF NOT EXISTS idx_comparisons_published    ON comparisons(is_published);
CREATE INDEX IF NOT EXISTS idx_comparisons_slug         ON comparisons(slug);
CREATE INDEX IF NOT EXISTS idx_affiliate_links_product  ON affiliate_links(product_id);
CREATE INDEX IF NOT EXISTS idx_affiliate_links_partner  ON affiliate_links(partner, country);
CREATE INDEX IF NOT EXISTS idx_pinterest_pins_comparison ON pinterest_pins(comparison_id);
CREATE INDEX IF NOT EXISTS idx_comparison_products_comp ON comparison_products(comparison_id);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================
ALTER TABLE categories         ENABLE ROW LEVEL SECURITY;
ALTER TABLE comparisons        ENABLE ROW LEVEL SECURITY;
ALTER TABLE products           ENABLE ROW LEVEL SECURITY;
ALTER TABLE comparison_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE affiliate_links    ENABLE ROW LEVEL SECURITY;
ALTER TABLE pinterest_pins     ENABLE ROW LEVEL SECURITY;

-- Lecture publique (anon key) — uniquement le contenu publié
CREATE POLICY "Public read categories"
  ON categories FOR SELECT
  USING (is_active = true);

CREATE POLICY "Public read comparisons"
  ON comparisons FOR SELECT
  USING (is_published = true);

CREATE POLICY "Public read products"
  ON products FOR SELECT
  USING (true);

CREATE POLICY "Public read comparison_products"
  ON comparison_products FOR SELECT
  USING (true);

CREATE POLICY "Public read affiliate_links"
  ON affiliate_links FOR SELECT
  USING (true);

CREATE POLICY "Public read pinterest_pins"
  ON pinterest_pins FOR SELECT
  USING (true);

-- Écriture complète pour service_role (scripts Python / GitHub Actions)
-- Note : service_role bypasse RLS par défaut dans Supabase — ces policies
-- sont ajoutées pour clarté et défense en profondeur si le bypass est désactivé.
CREATE POLICY "Service role full access categories"
  ON categories FOR ALL
  USING     (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "Service role full access comparisons"
  ON comparisons FOR ALL
  USING     (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "Service role full access products"
  ON products FOR ALL
  USING     (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "Service role full access comparison_products"
  ON comparison_products FOR ALL
  USING     (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "Service role full access affiliate_links"
  ON affiliate_links FOR ALL
  USING     (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "Service role full access pinterest_pins"
  ON pinterest_pins FOR ALL
  USING     (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- ============================================================
-- FONCTIONS UTILITAIRES
-- ============================================================

-- Mise à jour automatique de last_updated sur comparisons
CREATE OR REPLACE FUNCTION update_comparison_last_updated()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.last_updated = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER trigger_comparison_last_updated
  BEFORE UPDATE ON comparisons
  FOR EACH ROW
  EXECUTE FUNCTION update_comparison_last_updated();

-- Mise à jour automatique de last_checked sur affiliate_links
CREATE OR REPLACE FUNCTION update_affiliate_last_checked()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.last_checked = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER trigger_affiliate_last_checked
  BEFORE UPDATE ON affiliate_links
  FOR EACH ROW
  WHEN (OLD.price IS DISTINCT FROM NEW.price OR OLD.in_stock IS DISTINCT FROM NEW.in_stock)
  EXECUTE FUNCTION update_affiliate_last_checked();
