-- Migration: ajout de product_url (lien direct marchand) et awin_category (catégorie Awin normalisée)
-- product_url = merchant_deep_link du flux Awin, utilisé pour validation des liens (sans consommer le clic affilié)
-- awin_category = category_name du flux Awin (hiérarchique, e.g. "Electronics > Mobile Phones > Smartphones")

ALTER TABLE products ADD COLUMN IF NOT EXISTS product_url    text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS awin_category  text;
