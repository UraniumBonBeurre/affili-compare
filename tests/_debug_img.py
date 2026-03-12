from pathlib import Path
from dotenv import load_dotenv
import os, supabase as sb, requests, io, hashlib
from urllib.parse import parse_qs, unquote, urlparse
from PIL import Image

load_dotenv(Path(__file__).parent.parent / '.env.local')
client = sb.create_client(
    os.environ["NEXT_PUBLIC_SUPABASE_URL"],
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"]
)

def resolve(url):
    if "productserve.com" in url and "url=" in url:
        qs = parse_qs(urlparse(url).query)
        raw = qs.get("url", [""])[0]
        if raw:
            return unquote(raw).replace("ssl:", "https:", 1)
    return url

def phash(url):
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    img = Image.open(io.BytesIO(resp.content)).convert("RGBA").resize((64, 64), Image.LANCZOS)
    return hashlib.md5(img.tobytes()).hexdigest(), resp.status_code, len(resp.content)

rows = client.table("products").select("name,image_url").eq("active", True).eq("merchant_key", "rue-du-commerce").limit(3).execute().data
for r in rows:
    raw = r["image_url"]
    real = resolve(raw)
    print("Product:", r['name'][:50])
    print("  RAW: ", raw[:90])
    print("  REAL:", real[:90])
    for label, url in [("proxy", raw), ("CDN", real)]:
        try:
            h, status, size = phash(url)
            print("    %s: status=%d size=%d hash=%s..." % (label, status, size, h[:12]))
        except Exception as e:
            print("    %s: ERROR %s" % (label, e))
    print()

ref_url = "https://media.rueducommerce.fr/mktp/product/a70a/6154/490c/47bd/a495/de52/77ee/a70a6154490c47bda495de5277ee3657.webp"
print("Reference placeholder:")
h, status, size = phash(ref_url)
print("  hash=%s  status=%d  size=%d" % (h[:12], status, size))
