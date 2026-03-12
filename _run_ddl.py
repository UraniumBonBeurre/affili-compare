#!/usr/bin/env python3
"""Execute DDL statements via Supabase session-mode pooler (service_role as password)."""
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from settings import SUPABASE_URL, SUPABASE_KEY  # SUPABASE_KEY = service_role

import re
m = re.match(r'https://([a-z0-9]+)\.supabase\.co', SUPABASE_URL)
if not m:
    print("Cannot extract project ref from SUPABASE_URL"); sys.exit(1)

ref = m.group(1)
# Transaction pooler — service_role key works as password
db_url = f"postgresql://postgres.{ref}:{SUPABASE_KEY}@aws-0-eu-west-3.pooler.supabase.com:6543/postgres"

sql = """
ALTER TABLE products
  DROP COLUMN IF EXISTS image_r2_key,
  DROP COLUMN IF EXISTS badge,
  DROP COLUMN IF EXISTS pros_fr,
  DROP COLUMN IF EXISTS cons_fr,
  DROP COLUMN IF EXISTS pros_en,
  DROP COLUMN IF EXISTS cons_en,
  DROP COLUMN IF EXISTS fts,
  DROP COLUMN IF EXISTS ean,
  DROP COLUMN IF EXISTS amazon_asin,
  DROP COLUMN IF EXISTS amazon_url,
  DROP COLUMN IF EXISTS mpn,
  DROP COLUMN IF EXISTS merchant_name,
  DROP COLUMN IF EXISTS rating,
  DROP COLUMN IF EXISTS review_count;
"""

print("Running DDL via Supabase transaction pooler...")
result = subprocess.run(
    ["psql", db_url, "-c", sql],
    capture_output=True, text=True
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
sys.exit(result.returncode)
