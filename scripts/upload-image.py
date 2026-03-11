#!/usr/bin/env python3
"""
upload-image.py — Upload a local image to Cloudflare R2

Usage:
    python scripts/upload-image.py path/to/image.jpg --key "pins/aspirateurs/test.jpg"
    python scripts/upload-image.py path/to/image.jpg --auto-key aspirateurs-sans-fil meilleures-aspirateurs

Environment variables required:
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_PUBLIC_URL

Bucket public access policy (Cloudflare Dashboard → R2 → Settings → Public Access):
    Enable "Allow Public Access" OR set up a custom domain.
    The public URL must match R2_PUBLIC_URL.
"""

import argparse
import mimetypes
import os
import sys
from datetime import datetime
from pathlib import Path

import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

# ── R2 credentials ────────────────────────────────────────────────────────────

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "").rstrip("/")

REQUIRED_VARS = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME", "R2_PUBLIC_URL"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_env() -> None:
    missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
    if missing:
        print(f"\033[1;31m✗ Variables manquantes : {', '.join(missing)}\033[0m")
        print("  Complète .env avec les valeurs du dashboard Cloudflare → R2")
        sys.exit(1)


def _build_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _auto_key(category_slug: str, comparison_slug: str) -> str:
    ym = datetime.now().strftime("%Y%m")
    return f"pins/{category_slug}/{comparison_slug}-{ym}.jpg"


def upload_file(local_path: str, key: str, check_exists: bool = True) -> str:
    """Upload to R2 and return public URL."""
    _check_env()

    path = Path(local_path)
    if not path.exists():
        print(f"\033[1;31m✗ Fichier introuvable : {local_path}\033[0m")
        sys.exit(1)

    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "application/octet-stream"
    size_kb = path.stat().st_size / 1024

    client = _build_r2_client()

    # Check if already uploaded
    if check_exists:
        try:
            client.head_object(Bucket=R2_BUCKET_NAME, Key=key)
            public_url = f"{R2_PUBLIC_URL}/{key}"
            print(f"\033[1;33m⚠  Déjà en R2 → {public_url}\033[0m")
            return public_url
        except client.exceptions.ClientError:
            pass  # Not found, proceed with upload

    print(f"\033[1;36m⬆  Upload en cours …\033[0m")
    print(f"   Fichier : {path.name}  ({size_kb:.1f} KB)")
    print(f"   Bucket  : {R2_BUCKET_NAME}")
    print(f"   Clé     : {key}")

    with open(path, "rb") as fh:
        client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=key,
            Body=fh.read(),
            ContentType=mime,
            CacheControl="public, max-age=2592000, immutable",
        )

    public_url = f"{R2_PUBLIC_URL}/{key}"
    print(f"\033[1;32m✓ Uploadé → {public_url}\033[0m")
    return public_url


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Upload une image vers Cloudflare R2")
    parser.add_argument("image", help="Chemin vers l'image locale à uploader")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--key", help="Clé R2 manuelle, ex: pins/aspirateurs/test.jpg")
    group.add_argument(
        "--auto-key",
        nargs=2,
        metavar=("CATEGORY_SLUG", "COMPARISON_SLUG"),
        help="Génère la clé automatiquement : pins/{category}/{comparison}-YYYYMM.jpg",
    )
    parser.add_argument(
        "--no-check",
        action="store_true",
        help="Uploader même si l'objet existe déjà (écrase)",
    )
    args = parser.parse_args()

    key = args.key if args.key else _auto_key(args.auto_key[0], args.auto_key[1])
    url = upload_file(args.image, key, check_exists=not args.no_check)
    # Print bare URL on last line for easy scripting
    print(url)


if __name__ == "__main__":
    main()
