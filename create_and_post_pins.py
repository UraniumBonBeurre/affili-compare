#!/usr/bin/env python3
"""
create_and_post_pins.py — Génère et publie des pins Pinterest pour les top_articles
=====================================================================================

PIPELINE :
  1. Récupère les top_articles qui n'ont pas encore assez de pins
  2. Pour chaque article, génère nb_pins_per_article visuels Pinterest (1000×1500 px)
  3. Si production_workflow : upload R2 + publish Pinterest API v5 + DB pinterest_pins
     Sinon : sauvegarde locale dans local_pinterest/

Usage :
    python3 scripts/create_and_post_pins.py                  # Articles sans pins
    python3 scripts/create_and_post_pins.py --slug top-gaming-setup-2026-07
    python3 scripts/create_and_post_pins.py --limit 5
    python3 scripts/create_and_post_pins.py --dry-run
"""

import argparse
import io
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    _PIL = True
except ImportError:
    _PIL = False

from settings import (
    ROOT, SUPABASE_URL, SUPABASE_KEY,
    OLLAMA_CLOUD_API_KEY, OLLAMA_CLOUD_HOST, OLLAMA_CLOUD_MODEL,
    HF_API_TOKEN, PINTEREST_ACCESS_TOKEN, PINTEREST_API_BASE, PINTEREST_BOARD_ID,
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_PUBLIC_URL,
    SITE_URL, FONTS_DIR, LOCAL_PINTEREST_DIR, TAXONOMY_PATH,
    production_workflow, nb_pins_per_article,
    sb_headers, check_supabase, get_board_for_niche,
)

# ── Constantes ────────────────────────────────────────────────────────────────
PIN_W, PIN_H = 1000, 1500
MAX_PINS_PER_DAY = 100
DELAY_BETWEEN_PINS = 30

MONTH_FR = {
    "01": "janvier", "02": "février",   "03": "mars",    "04": "avril",
    "05": "mai",     "06": "juin",      "07": "juillet", "08": "août",
    "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre",
}


# ── Supabase ──────────────────────────────────────────────────────────────────

def sb_get(path: str, params: str = "") -> list:
    url = f"{SUPABASE_URL}/rest/v1/{path}{'?' + params if params else ''}"
    r = requests.get(url, headers=sb_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def sb_upsert(table: str, row: dict) -> bool:
    h = sb_headers({"Prefer": "resolution=merge-duplicates,return=minimal"})
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, json=row, timeout=30)
    return r.status_code in (200, 201, 204)


# ── Taxonomie ─────────────────────────────────────────────────────────────────

def _load_taxonomy() -> dict:
    if TAXONOMY_PATH.exists():
        return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    return {}


# ── Fonts & Drawing ──────────────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False):
    candidates = (
        [FONTS_DIR / "Poppins-Bold.ttf", FONTS_DIR / "Montserrat-Bold.ttf",
         FONTS_DIR / "BebasNeue-Regular.ttf",
         Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")]
        if bold else
        [FONTS_DIR / "Montserrat-Medium.ttf", FONTS_DIR / "Poppins-Bold.ttf",
         Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
         Path("/System/Library/Fonts/Helvetica.ttc"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _wrap(text: str, font, max_w: int, draw) -> list:
    words = text.split()
    lines, cur = [], ""
    for word in words:
        test = f"{cur} {word}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _gradient_bg(top_color=(14, 20, 36), bot_color=(22, 32, 56)):
    img = Image.new("RGB", (PIN_W, PIN_H))
    draw = ImageDraw.Draw(img)
    r0, g0, b0 = top_color
    r1, g1, b1 = bot_color
    for y in range(PIN_H):
        t = y / PIN_H
        draw.line([(0, y), (PIN_W, y)], fill=(
            int(r0 + (r1 - r0) * t), int(g0 + (g1 - g0) * t), int(b0 + (b1 - b0) * t),
        ))
    return img


def _get_bg(image_style: str, top_color=(14, 20, 36), bot_color=(22, 32, 56)) -> "Image.Image":
    """Retourne l'image de fond : placeholder.jpg en test, HF sinon, gradient en dernier recours."""
    if not production_workflow:
        ph = ROOT / "public" / "placeholder.jpg"
        if ph.exists():
            return Image.open(ph).convert("RGB").resize((PIN_W, PIN_H), Image.LANCZOS)
    return _generate_bg_hf(image_style) or _gradient_bg(top_color, bot_color)


def _generate_bg_hf(prompt: str) -> Optional["Image.Image"]:
    if not HF_API_TOKEN:
        return None
    NO_TEXT = (
        "PURE PHOTOGRAPH. ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, NO SIGNS, "
        "NO LOGOS, NO WATERMARKS ANYWHERE IN THE IMAGE. "
        "Professional interior lifestyle photography only. Scene: "
    )
    url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": NO_TEXT + prompt.strip(),
               "parameters": {"width": PIN_W, "height": PIN_H}}
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            if resp.status_code == 200:
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                return img.resize((PIN_W, PIN_H), Image.LANCZOS)
            elif resp.status_code == 503:
                time.sleep(20 * (attempt + 1))
            elif resp.status_code == 429:
                time.sleep(60)
            else:
                print(f"     HF erreur {resp.status_code}: {resp.text[:100]}")
                break
        except Exception as e:
            print(f"     HF réseau: {e}")
            time.sleep(10)
    return None


def _draw_watermark(draw) -> None:
    font = _load_font(19)
    label = SITE_URL.replace("https://", "")
    w = draw.textbbox((0, 0), label, font=font)[2]
    draw.text((PIN_W - w - 28, PIN_H - 38), label, font=font, fill=(130, 155, 185))


# ── Pin Visual Variants ──────────────────────────────────────────────────────

def _make_hero(title: str, nb: int, niche_label: str,
               month_fr: str, year: str, image_style: str, save_to: Path) -> str:
    ACCENT, WHITE, LGRAY = (16, 185, 129), (255, 255, 255), (200, 220, 240)
    pad = 52
    bg = _get_bg(image_style, (14, 20, 38), (20, 35, 60))
    canvas = bg.copy()
    draw = ImageDraw.Draw(canvas)

    ov_h, ov_y = 430, PIN_H - 430
    blur_zone = bg.crop((0, ov_y - 30, PIN_W, PIN_H)).filter(ImageFilter.GaussianBlur(radius=6))
    canvas.paste(blur_zone, (0, ov_y - 30))
    overlay = Image.new("RGBA", (PIN_W, ov_h), (12, 18, 32, 218))
    canvas.paste(Image.new("RGB", (PIN_W, ov_h), (12, 18, 32)), (0, ov_y), overlay.split()[3])

    y = ov_y + 36
    bf = _load_font(21, bold=True)
    badge = f"✦  TOP {nb}  ·  {month_fr.upper()} {year}"
    bb = draw.textbbox((0, 0), badge, font=bf)
    bw, bh = bb[2] + 26, bb[3] + 14
    draw.rounded_rectangle([pad, y, pad + bw, y + bh], radius=6, fill=ACCENT)
    draw.text((pad + 13, y + 7), badge, font=bf, fill=WHITE)
    y += bh + 24

    tf = _load_font(50, bold=True)
    for line in _wrap(title, tf, PIN_W - 2 * pad, draw)[:3]:
        lh = draw.textbbox((0, 0), line, font=tf)[3]
        draw.text((pad + 2, y + 2), line, font=tf, fill=(0, 0, 0))
        draw.text((pad, y), line, font=tf, fill=WHITE)
        y += lh + 8
    y += 12

    sf = _load_font(27)
    sub = f"{nb} produits soigneusement sélectionnés pour {niche_label}"
    for line in _wrap(sub, sf, PIN_W - 2 * pad, draw)[:2]:
        draw.text((pad, y), line, font=sf, fill=LGRAY)
        y += draw.textbbox((0, 0), line, font=sf)[3] + 5

    draw.text((pad, PIN_H - 56), f"→  {SITE_URL.replace('https://', '')}/top",
              font=_load_font(22), fill=(100, 150, 190))
    _draw_watermark(draw)
    canvas.save(str(save_to), "JPEG", quality=90)
    return str(save_to)


def _make_spotlight(product: dict, title: str, niche_label: str,
                    month_fr: str, year: str, image_style: str, save_to: Path) -> str:
    ACCENT, WHITE, LGRAY = (16, 185, 129), (255, 255, 255), (190, 210, 230)
    pad = 52
    bg = _get_bg(image_style + ", warm afternoon light, cinematic", (28, 22, 48), (18, 14, 38))
    canvas = bg.copy()
    draw = ImageDraw.Draw(canvas)

    for y_row in range(260):
        draw.line([(0, y_row), (PIN_W, y_row)], fill=(12, 16, 28))

    ov_h, ov_y = 420, PIN_H - 420
    overlay = Image.new("RGBA", (PIN_W, ov_h), (10, 14, 26, 225))
    canvas.paste(Image.new("RGB", (PIN_W, ov_h), (10, 14, 26)), (0, ov_y), overlay.split()[3])

    draw.text((pad, 30), f"Pour {niche_label}  ·  {month_fr} {year}",
              font=_load_font(27), fill=(160, 220, 200))

    brand = (product.get("brand") or "").strip()
    if brand:
        draw.text((pad, 72), brand.upper(), font=_load_font(28), fill=ACCENT)

    name_f = _load_font(50, bold=True)
    name = (product.get("name") or "")[:70]
    y_n = 110
    for line in _wrap(name, name_f, PIN_W - 2 * pad, draw)[:2]:
        lh = draw.textbbox((0, 0), line, font=name_f)[3]
        draw.text((pad + 2, y_n + 2), line, font=name_f, fill=(0, 0, 0))
        draw.text((pad, y_n), line, font=name_f, fill=WHITE)
        y_n += lh + 8

    y = ov_y + 32
    price = product.get("price")
    if price:
        draw.text((pad, y), "À partir de", font=_load_font(23), fill=(150, 200, 185))
        y += 27
        pv_f = _load_font(58, bold=True)
        price_txt = f"{price} €"
        draw.text((pad, y), price_txt, font=pv_f, fill=ACCENT)
        y += draw.textbbox((0, 0), price_txt, font=pv_f)[3] + 18

    ctx_f = _load_font(27)
    for line in _wrap(f"Inclus dans : « {title[:55]} »", ctx_f, PIN_W - 2 * pad, draw)[:2]:
        draw.text((pad, y), line, font=ctx_f, fill=LGRAY)
        y += draw.textbbox((0, 0), line, font=ctx_f)[3] + 5

    _draw_watermark(draw)
    canvas.save(str(save_to), "JPEG", quality=90)
    return str(save_to)


# ── LLM for pin descriptions ────────────────────────────────────────────────

def _call_llm(prompt: str, max_tokens: int = 200) -> Optional[str]:
    if not OLLAMA_CLOUD_API_KEY:
        return None
    try:
        r = requests.post(
            f"{OLLAMA_CLOUD_HOST}/api/chat",
            headers={"Authorization": f"Bearer {OLLAMA_CLOUD_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": OLLAMA_CLOUD_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "stream": False,
                  "think": False,
                  "options": {"temperature": 0.55, "num_predict": max_tokens}},
            timeout=60,
        )
        if r.status_code == 200:
            text = r.json()["message"]["content"].strip()
            return re.sub(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+", "", text).strip()
    except Exception as e:
        print(f"  ⚠️  LLM: {e}")
    return None


def generate_pin_description(title: str, niche_label: str) -> tuple[str, str]:
    """Returns (fr_description, en_description) via a single bilingual LLM JSON call."""
    prompt = (
        f"Write a short Pinterest description (2-3 sentences, enthusiastic tone, with a call to action, NO hashtags) "
        f"for a pin linking to the article « {title} » about {niche_label}.\n\n"
        f"Return ONLY a JSON object with exactly two keys:\n"
        f"{{ \"fr\": \"<description in French>\", \"en\": \"<description in English>\" }}"
    )
    raw = _call_llm(prompt, 300)
    if raw:
        try:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                data = json.loads(m.group())
                fr_desc = data.get("fr", "").strip()
                en_desc = data.get("en", "").strip()
                if fr_desc and en_desc:
                    return fr_desc, en_desc
        except (json.JSONDecodeError, AttributeError):
            pass
    fallback_fr = f"Découvrez notre sélection pour {niche_label} — {title}"
    fallback_en = f"Discover our top picks for {niche_label} — {title}"
    return fallback_fr, fallback_en


# ── R2 Upload ────────────────────────────────────────────────────────────────

def upload_to_r2(image_path: Path, key: str) -> str:
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("  ⚠️  boto3 non installé")
        return ""

    if not all([R2_PUBLIC_URL, R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        print("  ⚠️  Variables R2 manquantes")
        return ""

    try:
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        with open(image_path, "rb") as f:
            client.put_object(
                Bucket=R2_BUCKET_NAME, Key=key, Body=f.read(),
                ContentType="image/jpeg",
                CacheControl="public, max-age=2592000, immutable",
            )
        public_url = f"{R2_PUBLIC_URL}/{key}"
        print(f"  ☁️  R2 → {public_url}")
        return public_url
    except Exception as e:
        print(f"  ⚠️  R2: {e}")
        return ""


# ── Pinterest API ────────────────────────────────────────────────────────────

def _publish_pin(board_id: str, title: str, description: str,
                 media_url: str, link: str) -> dict:
    if not PINTEREST_ACCESS_TOKEN:
        raise RuntimeError("PINTEREST_ACCESS_TOKEN manquant")
    r = requests.post(
        f"{PINTEREST_API_BASE}/pins",
        headers={"Authorization": f"Bearer {PINTEREST_ACCESS_TOKEN}",
                 "Content-Type": "application/json"},
        json={
            "board_id": board_id,
            "title": title[:100],
            "description": description[:500],
            "media_source": {"source_type": "image_url", "url": media_url},
            "link": link,
        },
        timeout=30,
    )
    if r.status_code == 401:
        raise RuntimeError("Pinterest token expiré")
    if r.status_code == 429:
        raise RuntimeError("Pinterest rate limit (429)")
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Pinterest API {r.status_code}: {r.text[:300]}")
    return r.json()


def count_pins_today() -> int:
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = sb_get("pinterest_pins", f"published_at=gte.{today_start}&select=id")
    return len(rows)


# ── Fetch articles needing pins ──────────────────────────────────────────────

def fetch_articles_needing_pins(limit: int = 10) -> list[dict]:
    """Trouve les top_articles récents qui n'ont pas encore nb_pins_per_article pins."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    articles = sb_get(
        "top_articles",
        f"created_at=gte.{cutoff}&select=*&order=created_at.desc&limit={limit * 3}",
    )
    if not articles:
        return []

    # Count existing pins per article URL
    article_urls = [a.get("url", "") for a in articles if a.get("url")]
    if not article_urls:
        return articles[:limit]

    existing_pins = sb_get(
        "pinterest_pins",
        f"select=link_to_article&published_at=gte.{cutoff}",
    )
    pin_counts: dict[str, int] = {}
    for p in existing_pins:
        link = p.get("link_to_article", "")
        pin_counts[link] = pin_counts.get(link, 0) + 1

    eligible = [
        a for a in articles
        if pin_counts.get(a.get("url", ""), 0) < nb_pins_per_article
    ]
    return eligible[:limit]


# ── Main orchestration ───────────────────────────────────────────────────────

def process_article(article: dict, taxonomy: dict, dry_run: bool = False) -> int:
    """Génère et (optionnellement) publie des pins pour un article. Retourne le nb de pins créés."""
    slug = article.get("slug", "")
    title = article.get("title", "")
    url = article.get("url", f"{SITE_URL}/top/{slug}")
    content_raw = article.get("content", "{}")

    try:
        content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
    except (json.JSONDecodeError, TypeError):
        content = {}

    niche = content.get("keyword", "")
    niche_label = content.get("subcategory", niche.replace("_", " "))
    month_str = content.get("month", datetime.now().strftime("%Y-%m"))
    products = content.get("products", [])

    year, mo = month_str.split("-") if "-" in month_str else (str(datetime.now().year), "01")
    month_fr = MONTH_FR.get(mo, mo)

    # Niche config from taxonomy
    niche_cfg = taxonomy.get("niche_config", {}).get(niche, {})
    image_style = niche_cfg.get(
        "image_style",
        f"Modern interior design for {niche_label}, cozy lifestyle photography, no text",
    )

    print(f"\n  📝 Article : {title}")
    print(f"     Niche: {niche}  |  Produits: {len(products)}")

    # Board routing
    board_name_fr, board_id_fr = get_board_for_niche(niche, "fr")
    board_name_en, board_id_en = get_board_for_niche(niche, "en")
    print(f"  🗂  Board FR : {board_name_fr} [{board_id_fr or 'ID à remplir'}]")
    print(f"  🗂  Board EN : {board_name_en} [{board_id_en or 'ID à remplir'}]")

    if not _PIL:
        print("  ⚠️  Pillow non disponible — pip install Pillow")
        return 0

    slug_safe = re.sub(r"[^a-z0-9-]", "", slug.lower())[:42]

    # Determine output dir
    if production_workflow:
        out_dir = ROOT / "output" / "top_pins"
    else:
        out_dir = ROOT / "public" / "local_pins" / slug_safe
    out_dir.mkdir(parents=True, exist_ok=True)

    nb_pins = min(nb_pins_per_article, 2)  # max 2 variants

    # Generate pin variants
    pin_paths: list[str] = []
    variants = []

    # Variant 1: Hero
    hero_path = out_dir / "hero.jpg"
    try:
        print(f"  🖼️  Génération Hero…")
        path = _make_hero(
            title, len(products), niche_label, month_fr, year,
            image_style, hero_path,
        )
        pin_paths.append(path)
        variants.append("hero")
        print(f"     → {hero_path.name}")
    except Exception as e:
        print(f"  ⚠️  Hero échoué: {e}")

    # Variant 2: Spotlight (if nb_pins >= 2 and products available)
    if nb_pins >= 2 and products:
        spot_path = out_dir / "spotlight.jpg"
        try:
            print(f"  🖼️  Génération Spotlight…")
            path = _make_spotlight(
                products[0], title, niche_label, month_fr, year,
                image_style, spot_path,
            )
            pin_paths.append(path)
            variants.append("spotlight")
            print(f"     → {spot_path.name}")
        except Exception as e:
            print(f"  ⚠️  Spotlight échoué: {e}")

    if not pin_paths:
        print("  ⚠️  Aucun visuel généré")
        return 0

    # Generate bilingual description
    description_fr, description_en = generate_pin_description(title, niche_label)

    # Publish or save locally
    published = 0
    if production_workflow and not dry_run:
        for i, (local_path, variant) in enumerate(zip(pin_paths, variants)):
            r2_key = f"pins/top/{slug_safe}_{variant}.jpg"
            r2_url = upload_to_r2(Path(local_path), r2_key)
            if not r2_url:
                continue
            # Publish FR pin to FR board
            try:
                target_board = board_id_fr or PINTEREST_BOARD_ID
                pin = _publish_pin(
                    board_id=target_board,
                    title=title,
                    description=description_fr,
                    media_url=r2_url,
                    link=url,
                )
                pin_id = pin.get("id", "")
                pin_url = f"https://www.pinterest.com/pin/{pin_id}/"
                print(f"  📌 Pin FR publié ({variant}): {pin_url}")
                sb_upsert("pinterest_pins", {
                    "pin_id": pin_id,
                    "url": pin_url,
                    "board_id": target_board,
                    "title": title[:100],
                    "background_text": image_style[:200],
                    "description": description_fr[:500],
                    "link_to_article": url,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                published += 1
            except Exception as e:
                print(f"  ⚠️  Pinterest FR ({variant}): {e}")
            # Publish EN pin to EN board
            try:
                target_board_en = board_id_en or PINTEREST_BOARD_ID
                title_en = content.get("title_en", title)
                pin_en = _publish_pin(
                    board_id=target_board_en,
                    title=title_en,
                    description=description_en,
                    media_url=r2_url,
                    link=url,
                )
                pin_id_en = pin_en.get("id", "")
                pin_url_en = f"https://www.pinterest.com/pin/{pin_id_en}/"
                print(f"  📌 Pin EN publié ({variant}): {pin_url_en}")
                sb_upsert("pinterest_pins", {
                    "pin_id": pin_id_en,
                    "url": pin_url_en,
                    "board_id": target_board_en,
                    "title": title_en[:100],
                    "background_text": image_style[:200],
                    "description": description_en[:500],
                    "link_to_article": url,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                published += 1
            except Exception as e:
                print(f"  ⚠️  Pinterest EN ({variant}): {e}")
            if i < len(pin_paths) - 1:
                time.sleep(DELAY_BETWEEN_PINS)
    elif dry_run:
        for local_path, variant in zip(pin_paths, variants):
            print(f"  [DRY-RUN] {variant} → {Path(local_path).name}")
            print(f"    DESC FR: {description_fr[:80]}…")
            print(f"    DESC EN: {description_en[:80]}…")
        published = len(pin_paths)
    else:
        print(f"  💾 {len(pin_paths)} visuel(s) sauvés dans {out_dir}/")
        # Écriture pin.txt
        pin_lines = [
            f"SLUG: {slug}",
            f"LIEN ARTICLE: {url}",
            "",
            f"--- DESCRIPTION FR ---",
            description_fr,
            "",
            f"--- DESCRIPTION EN ---",
            description_en,
            "",
            "--- PRODUITS ---",
        ]
        for p in products:
            aff = p.get("affiliate_url") or p.get("url") or "#"
            pin_lines.append(f"  {p.get('name', '?')} → {aff}")
        try:
            (out_dir / "pin.txt").write_text("\n".join(pin_lines), encoding="utf-8")
            print(f"  📄 pin.txt → {out_dir}/pin.txt")
        except Exception as e:
            print(f"  ⚠️  pin.txt: {e}")
        published = len(pin_paths)

    return published


def main():
    parser = argparse.ArgumentParser(description="Génère et publie des pins pour les top_articles")
    parser.add_argument("--slug", default=None, help="Traiter un article spécifique par slug")
    parser.add_argument("--limit", type=int, default=3, help="Max articles à traiter (défaut: 3)")
    parser.add_argument("--dry-run", action="store_true", help="Aucune publication ni écriture DB")
    args = parser.parse_args()

    check_supabase()

    publish_mode = "Pinterest + R2" if production_workflow else "local seulement"
    print(f"\n{'═'*62}")
    print(f"  📌  create_and_post_pins.py — {nb_pins_per_article} pins/article")
    print(f"  Publish : {publish_mode}")
    if args.dry_run:
        print("  Mode    : DRY-RUN")
    print(f"{'═'*62}\n")

    taxonomy = _load_taxonomy()

    # Check daily limit
    if production_workflow and not args.dry_run:
        pins_today = count_pins_today()
        if pins_today >= MAX_PINS_PER_DAY:
            print(f"  ⚠️  Limite journalière atteinte ({pins_today}/{MAX_PINS_PER_DAY})")
            return
        remaining = MAX_PINS_PER_DAY - pins_today
        print(f"  Pins aujourd'hui: {pins_today}/{MAX_PINS_PER_DAY}  →  max {remaining} restants\n")

    # Fetch articles
    if args.slug:
        articles = sb_get("top_articles", f"slug=eq.{args.slug}&select=*")
        if not articles:
            print(f"  ❌ Article '{args.slug}' introuvable")
            return
    else:
        articles = fetch_articles_needing_pins(limit=args.limit)

    if not articles:
        print("  ✅ Aucun article n'a besoin de pins")
        return

    print(f"  📋 {len(articles)} article(s) à traiter :")
    for a in articles:
        print(f"     • {a.get('title', a.get('slug', '?'))[:60]}")

    total_pins = 0
    for i, article in enumerate(articles, 1):
        print(f"\n{'─'*62}")
        print(f"  [{i}/{len(articles)}]")
        total_pins += process_article(article, taxonomy, dry_run=args.dry_run)

    print(f"\n{'═'*62}")
    print(f"  ✅ {total_pins} pin(s) {'créé(s)' if not args.dry_run else 'simulé(s)'}")
    print(f"{'═'*62}\n")


if __name__ == "__main__":
    main()
