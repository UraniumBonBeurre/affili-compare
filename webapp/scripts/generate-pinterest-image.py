#!/usr/bin/env python3
"""
generate-pinterest-image.py — Génère une image Pinterest 1000×1500px

Pipeline :
  1. Appel à Hugging Face Inference API (FLUX.1-schnell ou SDXL-turbo)
  2. Overlay Pillow : fond semi-transparent + titre + prix + logo site
  3. Upload automatique vers Cloudflare R2
  4. Option --comparison-id : met à jour supabase.comparisons.pin_image_url

Usage :
    python scripts/generate-pinterest-image.py \\
        --title "Top 5 Aspirateurs Sans Fil 2025" \\
        --subtitle "Comparatif & Prix du moment" \\
        --price "dès 299 €" \\
        --output output/pins/aspirateurs.jpg

    python scripts/generate-pinterest-image.py \\
        --comparison-id 3 \\       # lit titre/prix depuis Supabase
        --upload                    # upload R2 + met à jour Supabase

Environment variables:
    HF_API_TOKEN          — huggingface.co/settings/tokens
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_PUBLIC_URL
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
"""

import argparse
import io
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter, ImageFont

load_dotenv()

# ── Constants ─────────────────────────────────────────────────────────────────

HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Pinterest format — 2:3 ratio, 1000×1500
PIN_WIDTH = 1000
PIN_HEIGHT = 1500

# HuggingFace models (in preference order)
HF_MODELS = [
    "black-forest-labs/FLUX.1-schnell",      # Best quality, free tier
    "stabilityai/stable-diffusion-xl-base-1.0",  # Fallback
]

HF_INFERENCE_URL = "https://api-inference.huggingface.co/models/{model}"

# Fonts — using assets/fonts if available, else system fallback
FONTS_DIR = Path(__file__).parent.parent / "assets" / "fonts"

# Brand colors
BRAND_GREEN = (16, 185, 129)       # emerald-500
DARK_OVERLAY = (15, 23, 42, 210)   # slate-900 at 82% opacity
WHITE = (255, 255, 255)
LIGHT_GRAY = (226, 232, 240)       # slate-200

# ── Image generation ──────────────────────────────────────────────────────────

def _build_prompt(title: str, category: str) -> str:
    """Build a lifestyle-oriented image generation prompt."""
    templates = {
        "aspirateur": (
            "Modern minimalist living room, white walls, hardwood floor, "
            "professional product photography aesthetic, soft natural lighting from window, "
            "clean Scandinavian interior design, lifestyle photography, "
            "no text, no watermark, high resolution, Pinterest style"
        ),
        "lampe": (
            "Cozy modern living room interior with warm ambient lighting, "
            "designer lamp centerpiece, soft bokeh background, "
            "Scandinavian minimalist decor, lifestyle home photography, "
            "no text, no watermark, high resolution, Pinterest style"
        ),
        "default": (
            "Modern clean product photography, white background, "
            "professional studio lighting, lifestyle e-commerce aesthetic, "
            "minimalist design, no text, high resolution, Pinterest style"
        ),
    }
    # Guess template from category
    cat = category.lower()
    if "aspir" in cat or "vacuum" in cat:
        template = templates["aspirateur"]
    elif "lamp" in cat or "lumi" in cat or "light" in cat:
        template = templates["lampe"]
    else:
        template = templates["default"]
    return template


def _generate_background_hf(prompt: str, max_retries: int = 3) -> Image.Image:
    """Call HF Inference API to generate background. Returns PIL Image."""
    headers = {
        "Authorization": f"Bearer {HF_API_TOKEN}",
        "Content-Type": "application/json",
    }

    for attempt in range(max_retries):
        for model in HF_MODELS:
            url = HF_INFERENCE_URL.format(model=model)
            payload = {
                "inputs": prompt,
                "parameters": {
                    "width": PIN_WIDTH,
                    "height": PIN_HEIGHT,
                    "num_inference_steps": 4 if "schnell" in model else 20,
                },
            }
            print(f"  🎨 HF {model} (tentative {attempt + 1}/{max_retries}) …")
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=120)
                if resp.status_code == 200:
                    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                    # Ensure correct size
                    if img.size != (PIN_WIDTH, PIN_HEIGHT):
                        img = img.resize((PIN_WIDTH, PIN_HEIGHT), Image.LANCZOS)
                    return img
                elif resp.status_code == 503:
                    # Model loading — wait
                    wait = min(30 * (attempt + 1), 90)
                    print(f"     Modèle en chargement. Attente {wait}s …")
                    time.sleep(wait)
                elif resp.status_code == 429:
                    print("     Rate limit HF. Attente 60s …")
                    time.sleep(60)
                else:
                    print(f"     Erreur HF {resp.status_code}: {resp.text[:200]}")
            except requests.RequestException as e:
                print(f"     Erreur réseau : {e}")
                time.sleep(10)

    raise RuntimeError("Impossible de générer l'image via HF après toutes les tentatives.")


def _fallback_gradient_bg(category: str) -> Image.Image:
    """Create a simple gradient background if HF fails."""
    img = Image.new("RGB", (PIN_WIDTH, PIN_HEIGHT), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Simple gradient: light green top → white center → light gray bottom
    for y in range(PIN_HEIGHT):
        progress = y / PIN_HEIGHT
        if progress < 0.4:
            r = int(236 + (255 - 236) * (progress / 0.4))
            g = int(253 + (255 - 253) * (progress / 0.4))
            b = int(240 + (255 - 240) * (progress / 0.4))
        else:
            r = int(255 - (255 - 248) * ((progress - 0.4) / 0.6))
            g = int(255 - (255 - 250) * ((progress - 0.4) / 0.6))
            b = int(255 - (255 - 252) * ((progress - 0.4) / 0.6))
        draw.line([(0, y), (PIN_WIDTH, y)], fill=(r, g, b))

    return img


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load font or fallback to default."""
    candidates = []
    if bold:
        candidates += [
            FONTS_DIR / "Inter-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    else:
        candidates += [
            FONTS_DIR / "Inter-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]

    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except (IOError, OSError):
            continue

    # Ultimate fallback
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def create_pin_image(
    title: str,
    subtitle: str,
    price: str = "",
    category: str = "default",
    site_name: str = "AffiliCompare.com",
    use_hf: bool = True,
) -> Image.Image:
    """
    Create a complete Pinterest pin image with text overlay.

    Layout (1000×1500 px):
      ┌──────────────────────────────┐
      │  [Background image HF/grad] │  ← 1000×1100
      ├──────────────────────────────┤
      │  Dark overlay panel          │
      │  ┌──────────────────────┐   │
      │  │ BADGE: "Comparatif"  │   │
      │  │ TITLE (bold, 52px)   │   │
      │  │ SUBTITLE (32px)      │   │
      │  │ PRICE (green, 44px)  │   │
      │  │ SITE NAME (20px)     │   │
      │  └──────────────────────┘   │
      └──────────────────────────────┘
    """
    # 1. Generate or create background
    if use_hf and HF_API_TOKEN:
        try:
            prompt = _build_prompt(title, category)
            bg = _generate_background_hf(prompt)
        except RuntimeError as e:
            print(f"  ⚠  HF échoué : {e}. Fallback dégradé.")
            bg = _fallback_gradient_bg(category)
    else:
        print("  ⚠  HF_API_TOKEN absent. Utilisation du dégradé de secours.")
        bg = _fallback_gradient_bg(category)

    # 2. Composite with dark overlay panel at bottom 500px
    canvas = bg.copy()
    overlay_height = 520
    overlay_top = PIN_HEIGHT - overlay_height

    # Slight blur on background behind text for legibility
    blur_region = bg.crop((0, overlay_top - 40, PIN_WIDTH, PIN_HEIGHT))
    blur_region = blur_region.filter(ImageFilter.GaussianBlur(radius=8))
    canvas.paste(blur_region, (0, overlay_top - 40))

    # Dark semi-transparent overlay
    overlay = Image.new("RGBA", (PIN_WIDTH, overlay_height), DARK_OVERLAY)
    canvas.paste(Image.new("RGB", (PIN_WIDTH, overlay_height), (15, 23, 42)), (0, overlay_top), overlay)

    # 3. Draw text
    draw = ImageDraw.Draw(canvas)

    pad_x = 52
    text_width = PIN_WIDTH - (pad_x * 2)
    y = overlay_top + 40

    # Badge "Comparatif ✓"
    badge_font = _load_font(22, bold=True)
    badge_text = "✓  COMPARATIF INDÉPENDANT"
    badge_bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_w = badge_bbox[2] + 28
    badge_h = badge_bbox[3] + 14
    draw.rounded_rectangle(
        [pad_x, y, pad_x + badge_w, y + badge_h],
        radius=6,
        fill=BRAND_GREEN,
    )
    draw.text((pad_x + 14, y + 7), badge_text, font=badge_font, fill=WHITE)
    y += badge_h + 28

    # Title (bold, multi-line)
    title_font = _load_font(54, bold=True)
    title_lines = _wrap_text(title, title_font, text_width, draw)
    for line in title_lines[:3]:  # max 3 lines
        draw.text((pad_x, y), line, font=title_font, fill=WHITE)
        bbox = draw.textbbox((0, 0), line, font=title_font)
        y += bbox[3] + 8
    y += 12

    # Subtitle
    if subtitle:
        sub_font = _load_font(32)
        sub_lines = _wrap_text(subtitle, sub_font, text_width, draw)
        for line in sub_lines[:2]:
            draw.text((pad_x, y), line, font=sub_font, fill=LIGHT_GRAY)
            bbox = draw.textbbox((0, 0), line, font=sub_font)
            y += bbox[3] + 6
        y += 10

    # Price (green, prominent)
    if price:
        price_font = _load_font(48, bold=True)
        draw.text((pad_x, y), price, font=price_font, fill=tuple(BRAND_GREEN))
        bbox = draw.textbbox((0, 0), price, font=price_font)
        y += bbox[3] + 16

    # Separator line
    draw.line([(pad_x, y), (PIN_WIDTH - pad_x, y)], fill=(71, 85, 105), width=1)
    y += 16

    # Site name
    site_font = _load_font(22)
    draw.text((pad_x, y), f"🔗 {site_name}", font=site_font, fill=(148, 163, 184))

    return canvas


# ── R2 upload helper (optional dependency) ────────────────────────────────────

def _upload_to_r2(image_path: Path, key: str) -> str:
    """Upload image to R2 using boto3. Returns public URL."""
    try:
        import boto3
        from botocore.config import Config

        r2_url = os.getenv("R2_PUBLIC_URL", "").rstrip("/")
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
            aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        with open(image_path, "rb") as f:
            client.put_object(
                Bucket=os.getenv("R2_BUCKET_NAME"),
                Key=key,
                Body=f.read(),
                ContentType="image/jpeg",
                CacheControl="public, max-age=2592000, immutable",
            )
        public_url = f"{r2_url}/{key}"
        print(f"  ✅ Uploadé R2 → {public_url}")
        return public_url
    except Exception as e:
        print(f"  ⚠  Upload R2 échoué : {e}")
        return ""


def _update_supabase_pin_image(comparison_id: int, image_url: str) -> None:
    """Update comparisons.pin_image_url in Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("  ⚠  SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY absent. Mise à jour ignorée.")
        return
    try:
        resp = requests.patch(
            f"{SUPABASE_URL}/rest/v1/comparisons?id=eq.{comparison_id}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={"pin_image_url": image_url},
            timeout=10,
        )
        resp.raise_for_status()
        print(f"  ✅ Supabase mis à jour : comparisons.pin_image_url = {image_url}")
    except Exception as e:
        print(f"  ⚠  Mise à jour Supabase échouée : {e}")


def _fetch_comparison_from_supabase(comparison_id: int) -> dict:
    """Fetch comparison title/price from Supabase."""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/comparisons?id=eq.{comparison_id}&select=title,slug,meta_description,category_id",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        },
        timeout=10,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise ValueError(f"Comparison {comparison_id} non trouvée dans Supabase")
    return rows[0]


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Génère une image Pinterest 1000×1500 px pour AffiliCompare"
    )
    parser.add_argument("--title", help="Titre principal (bold, large)")
    parser.add_argument("--subtitle", default="", help="Sous-titre")
    parser.add_argument("--price", default="", help="Prix affiché (ex: 'dès 299 €')")
    parser.add_argument("--category", default="default", help="Catégorie (aspir, lampe, default)")
    parser.add_argument(
        "--comparison-id",
        type=int,
        help="ID Supabase : lit titre/meta automatiquement",
    )
    parser.add_argument(
        "--output",
        default="output/pins/pin.jpg",
        help="Chemin de sortie local (défaut: output/pins/pin.jpg)",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload vers R2 et met à jour Supabase si --comparison-id fourni",
    )
    parser.add_argument(
        "--no-hf",
        action="store_true",
        help="Désactive HF API, utilise le fond dégradé (test rapide)",
    )
    args = parser.parse_args()

    # Fetch from Supabase if comparison-id provided
    if args.comparison_id:
        if not SUPABASE_URL:
            print("\033[1;31m✗ SUPABASE_URL requis pour --comparison-id\033[0m")
            sys.exit(1)
        print(f"  📡 Lecture Supabase comparison #{args.comparison_id} …")
        comp = _fetch_comparison_from_supabase(args.comparison_id)
        title = args.title or comp.get("title", "Comparatif Produits 2025")
        subtitle = args.subtitle or comp.get("meta_description", "")[:80]
    else:
        if not args.title:
            parser.error("--title requis (ou --comparison-id)")
        title = args.title
        subtitle = args.subtitle

    # Generate image
    print(f"\n\033[1;34m🎨 Génération image Pinterest …\033[0m")
    print(f"   Titre   : {title}")
    print(f"   Sous-t. : {subtitle}")
    print(f"   Prix    : {args.price}")

    img = create_pin_image(
        title=title,
        subtitle=subtitle,
        price=args.price,
        category=args.category,
        use_hf=not args.no_hf,
    )

    # Save locally
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), "JPEG", quality=92, optimize=True)
    print(f"\n\033[1;32m✓ Image sauvée : {out_path}  ({out_path.stat().st_size / 1024:.0f} KB)\033[0m")

    # Upload to R2
    if args.upload:
        # Build key from comparison or filename
        if args.comparison_id:
            slug = comp.get("slug", f"comparison-{args.comparison_id}")
            from datetime import datetime
            ym = datetime.now().strftime("%Y%m")
            key = f"pins/{args.category}/{slug}-{ym}.jpg"
        else:
            key = f"pins/manual/{out_path.stem}.jpg"

        public_url = _upload_to_r2(out_path, key)
        if public_url and args.comparison_id:
            _update_supabase_pin_image(args.comparison_id, public_url)

    print()


if __name__ == "__main__":
    main()
