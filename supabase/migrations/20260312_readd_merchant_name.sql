-- Re-add merchant_name column (was dropped in 20260312_drop_unused_product_columns.sql)
ALTER TABLE products ADD COLUMN IF NOT EXISTS merchant_name text;
