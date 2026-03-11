#!/usr/bin/env python3
"""
publish-pinterest.py — Publie automatiquement des pins sur Pinterest

Pipeline :
  1. Requête Supabase : comparisons publiées SANS pin dans les 7 derniers jours
  2. Pour chaque comparison :
       a. Génère l'image (generate-pinterest-image.py pipeline)
       b. Upload vers R2
       c. POST pin via Pinterest API v5
       d. Enregistre pin_id + board_id dans supabase.pinterest_pins
  3. Rate limiting : max 100 pins/jour, 30s entre chaque appel

Usage :
    python scripts/publish-pinterest.py               # Publie tous les pins en attente
    python scripts/publish-pinterest.py --dry-run      # Simule sans publier
    python scripts/publish-pinterest.py --comparison-id 3  # Force un comparison spécifique
    python scripts/publish-pinterest.py --limit 5      # Max 5 pins cette exécution

Environment variables:
    PINTEREST_ACCESS_TOKEN   — OAuth2 access token Pinterest
    PINTEREST_BOARD_ID       — ID du board de destination (ex: 123456789)
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_PUBLIC_URL
    HF_API_TOKEN             — pour génération image (optionnel si --skip-image-gen)
    SITE_URL                 — URL de base du site (ex: https://affili-compare.com)
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

PINTEREST_ACCESS_TOKEN = os.getenv("PINTEREST_ACCESS_TOKEN", "")
PINTEREST_BOARD_ID = os.getenv("PINTEREST_BOARD_ID", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SITE_URL = os.getenv("SITE_URL", "https://affili-compare.com").rstrip("/")

PINTEREST_API_BASE = "https://api.pinterest.com/v5"
MAX_PINS_PER_DAY = 100
DELAY_BETWEEN_PINS_S = 30  # Pinterest rate limit safety margin


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _sb_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def fetch_comparisons_without_recent_pin(limit: int = 10) -> list[dict]:
    """
    Returns comparisons that:
      - status = 'published'
      - NO pinterest_pins row with published_at > (now - 7 days)
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    # Get all published comparisons with their latest pin date
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/comparisons"
        "?status=eq.published"
        "&select=id,title,slug,meta_description,category_id,categories(slug),pin_image_url"
        f"&order=updated_at.desc&limit={limit * 3}",
        headers=_sb_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    comparisons = resp.json()

    # Get recent pins (last 7 days)
    pins_resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/pinterest_pins"
        f"?published_at=gte.{cutoff}"
        "&select=comparison_id",
        headers=_sb_headers(),
        timeout=10,
    )
    pins_resp.raise_for_status()
    recently_pinned_ids = {p["comparison_id"] for p in pins_resp.json()}

    # Filter out recently pinned
    eligible = [c for c in comparisons if c["id"] not in recently_pinned_ids]
    return eligible[:limit]


def count_pins_today() -> int:
    """Count pins published today (UTC) to enforce daily limit."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/pinterest_pins?published_at=gte.{today_start}&select=id",
        headers=_sb_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return len(resp.json())


def save_pin_to_supabase(comparison_id: int, pin_id: str, board_id: str, image_url: str, pin_url: str) -> None:
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/pinterest_pins",
        headers=_sb_headers(),
        json={
            "comparison_id": comparison_id,
            "pin_id": pin_id,
            "board_id": board_id,
            "image_url": image_url,
            "pin_url": pin_url,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "status": "published",
        },
        timeout=10,
    )
    resp.raise_for_status()


# ── Pinterest API v5 ──────────────────────────────────────────────────────────

def _pinterest_headers() -> dict:
    return {
        "Authorization": f"Bearer {PINTEREST_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def publish_pin(
    board_id: str,
    title: str,
    description: str,
    media_url: str,
    link: str,
) -> dict:
    """
    POST /pins via Pinterest API v5.
    Returns the created pin object.
    """
    payload = {
        "board_id": board_id,
        "title": title[:100],   # Pinterest title limit
        "description": description[:500],
        "media_source": {
            "source_type": "image_url",
            "url": media_url,
        },
        "link": link,
    }

    resp = requests.post(
        f"{PINTEREST_API_BASE}/pins",
        headers=_pinterest_headers(),
        json=payload,
        timeout=30,
    )

    if resp.status_code == 401:
        raise RuntimeError(
            "Pinterest token expiré ou invalide. "
            "Regénère un token via scripts/refresh_pinterest_token.py ou l'OAuth flow."
        )
    if resp.status_code == 429:
        raise RuntimeError("Pinterest rate limit atteint (429). Attends avant de réessayer.")
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Pinterest API erreur {resp.status_code}: {resp.text[:400]}")

    return resp.json()


# ── Image generation + R2 upload ─────────────────────────────────────────────

def generate_and_upload_image(comparison: dict) -> str:
    """
    Calls generate-pinterest-image.py pipeline inline (no subprocess).
    Returns R2 public URL.
    """
    # Inline import to avoid circular deps
    sys.path.insert(0, str(__file__))

    from pathlib import Path
    import importlib.util

    gen_script = Path(__file__).parent / "generate-pinterest-image.py"
    spec = importlib.util.spec_from_file_location("gen_img", str(gen_script))
    gen_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen_module)

    title = comparison.get("title", "")
    subtitle = comparison.get("meta_description", "")[:80]
    category_slug = comparison.get("categories", {}).get("slug", "default") if comparison.get("categories") else "default"

    # Cheapest price — query Supabase
    try:
        price_resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/affiliate_links"
            f"?comparison_id=eq.{comparison['id']}&select=price&order=price.asc&limit=1",
            headers=_sb_headers(),
            timeout=5,
        )
        rows = price_resp.json()
        price_str = f"dès {rows[0]['price']:.0f} €" if rows and rows[0].get("price") else ""
    except Exception:
        price_str = ""

    img = gen_module.create_pin_image(
        title=title,
        subtitle=subtitle,
        price=price_str,
        category=category_slug,
    )

    # Save to /tmp
    from pathlib import Path
    from datetime import datetime
    slug = comparison.get("slug", f"comparison-{comparison['id']}")
    ym = datetime.now().strftime("%Y%m")
    tmp_path = Path(f"/tmp/pin-{slug}-{ym}.jpg")
    img.save(str(tmp_path), "JPEG", quality=92, optimize=True)

    key = f"pins/{category_slug}/{slug}-{ym}.jpg"
    public_url = gen_module._upload_to_r2(tmp_path, key)

    # Update Supabase pin_image_url
    if public_url:
        gen_module._update_supabase_pin_image(comparison["id"], public_url)

    return public_url


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Publie des pins Pinterest pour AffiliCompare")
    parser.add_argument("--dry-run", action="store_true", help="Simule sans publier")
    parser.add_argument("--comparison-id", type=int, help="Force un ID comparison spécifique")
    parser.add_argument("--limit", type=int, default=3, help="Max pins à publier (défaut: 3)")
    parser.add_argument("--skip-image-gen", action="store_true", help="Réutilise pin_image_url existante (ne génère pas d'image)")
    args = parser.parse_args()

    print(f"\n\033[1;35m📌 AffiliCompare — Publish Pinterest Pins\033[0m")
    print(f"   Mode  : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"   Limit : {args.limit}")
    print()

    # Validate required vars
    missing = []
    if not PINTEREST_ACCESS_TOKEN:
        missing.append("PINTEREST_ACCESS_TOKEN")
    if not PINTEREST_BOARD_ID:
        missing.append("PINTEREST_BOARD_ID")
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if missing:
        print(f"\033[1;31m✗ Variables manquantes : {', '.join(missing)}\033[0m")
        sys.exit(1)

    # Check daily limit
    pins_today = count_pins_today()
    if pins_today >= MAX_PINS_PER_DAY:
        print(f"\033[1;33m⚠  Limite journalière atteinte ({pins_today}/{MAX_PINS_PER_DAY}). Arrêt.\033[0m")
        sys.exit(0)

    remaining_today = MAX_PINS_PER_DAY - pins_today
    limit = min(args.limit, remaining_today)
    print(f"   Pins aujourd'hui : {pins_today}/{MAX_PINS_PER_DAY}  →  max {limit} ce run\n")

    # Fetch comparisons
    if args.comparison_id:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/comparisons"
            f"?id=eq.{args.comparison_id}"
            "&select=id,title,slug,meta_description,categories(slug),pin_image_url",
            headers=_sb_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        comparisons = resp.json()
    else:
        comparisons = fetch_comparisons_without_recent_pin(limit=limit)

    if not comparisons:
        print("\033[1;33m  Aucune comparison à publier (tous déjà pinnés ou aucune publiée).\033[0m")
        sys.exit(0)

    print(f"  → {len(comparisons)} comparison(s) à publier :")
    for c in comparisons:
        print(f"     #{c['id']} {c['title']}")
    print()

    published = 0
    for i, comp in enumerate(comparisons):
        slug = comp.get("slug", "")
        title = comp.get("title", "")
        description = comp.get("meta_description") or f"Comparatif {title} — meilleurs prix et avis"
        category_slug = comp.get("categories", {}).get("slug", "") if comp.get("categories") else ""
        comparison_url = f"{SITE_URL}/fr/{category_slug}/{slug}" if category_slug else f"{SITE_URL}/fr/{slug}"

        print(f"\033[1;34m[{i+1}/{len(comparisons)}] {title}\033[0m")

        # 1. Image
        if args.skip_image_gen and comp.get("pin_image_url"):
            image_url = comp["pin_image_url"]
            print(f"   Image existante : {image_url}")
        else:
            print("   Génération image …")
            try:
                image_url = generate_and_upload_image(comp)
            except Exception as e:
                print(f"   \033[1;31m✗ Génération image échouée : {e}\033[0m  → Ignoré")
                continue

        if not image_url:
            print("   \033[1;31m✗ URL image vide → Ignoré\033[0m")
            continue

        # 2. Publish
        if args.dry_run:
            print(f"   [DRY RUN] Publierait pin :")
            print(f"     Titre       : {title}")
            print(f"     Description : {description[:80]}…")
            print(f"     Image URL   : {image_url}")
            print(f"     Link        : {comparison_url}")
            print(f"     Board ID    : {PINTEREST_BOARD_ID}")
        else:
            try:
                pin = publish_pin(
                    board_id=PINTEREST_BOARD_ID,
                    title=title,
                    description=description,
                    media_url=image_url,
                    link=comparison_url,
                )
                pin_id = pin.get("id", "unknown")
                pin_url = f"https://pinterest.com/pin/{pin_id}/"
                print(f"   \033[1;32m✓ Pin publié : {pin_url}\033[0m")

                save_pin_to_supabase(
                    comparison_id=comp["id"],
                    pin_id=pin_id,
                    board_id=PINTEREST_BOARD_ID,
                    image_url=image_url,
                    pin_url=pin_url,
                )
            except RuntimeError as e:
                print(f"   \033[1;31m✗ Erreur Pinterest : {e}\033[0m")
                if "expiré" in str(e) or "invalide" in str(e):
                    print("   → Arrêt (token invalide).")
                    sys.exit(1)
                continue

        published += 1

        # Rate limit delay (skip after last pin)
        if i < len(comparisons) - 1:
            print(f"   ⏳ Attente {DELAY_BETWEEN_PINS_S}s …")
            time.sleep(DELAY_BETWEEN_PINS_S)

    print(f"\n\033[1;32m✅ {published} pin(s) {'simulé(s)' if args.dry_run else 'publié(s)'}\033[0m\n")


if __name__ == "__main__":
    main()
