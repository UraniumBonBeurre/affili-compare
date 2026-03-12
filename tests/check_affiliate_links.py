#!/usr/bin/env python3
"""
check_affiliate_links.py — Détecte les images placeholder par comparaison de pixels.
======================================================================================

Télécharge une image de référence par marchand, puis compare pixel-à-pixel (hash MD5
d'un redimensionnement 64×64 RGBA) chaque image produit à cette référence.

Merchants sans référence → badge "?" (contrôle non effectué).

Usage :
    python3 tests/check_affiliate_links.py
"""

import hashlib
import html as html_mod
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests
from dotenv import load_dotenv
from PIL import Image

# ── Path / env ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local")

import supabase as sb  # noqa: E402

_SUPABASE_URL = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
_SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"]
)
_client = sb.create_client(_SUPABASE_URL, _SUPABASE_KEY)

OUTPUT_HTML = Path(__file__).resolve().parent / "output" / "check_links.html"

# ── Images de référence placeholder (lues depuis placeholder_images.json) ────
# Source unique : src/config/placeholder_images.json
# Pour ajouter un marchand : ajouter une entrée dans ce JSON.
_PLACEHOLDER_JSON = ROOT / "src" / "config" / "placeholder_images.json"

def _load_placeholder_ref_urls() -> dict[str, list[str]]:
    try:
        raw = json.loads(_PLACEHOLDER_JSON.read_text(encoding="utf-8"))
        return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, list)}
    except Exception as e:
        print(f"  ⚠️  Impossible de charger {_PLACEHOLDER_JSON}: {e}")
        return {}

PLACEHOLDER_REF_URLS: dict[str, list[str]] = _load_placeholder_ref_urls()

# ── Constantes ────────────────────────────────────────────────────────────────
_NORM      = (64, 64)  # taille de normalisation pour comparaison
_HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; AffiliChecker/1.0)"}
_TIMEOUT   = 12
_WORKERS   = 30


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_image_url(url: str) -> str:
    """Décode productserve.com?url=ssl%3A... → vraie URL CDN directe."""
    if not url:
        return url
    if "productserve.com" in url and "url=" in url:
        try:
            qs = parse_qs(urlparse(url).query)
            raw = qs.get("url", [""])[0]
            if raw:
                decoded = unquote(raw)
                # ssl://host ou ssl:host → https://host
                if decoded.startswith("ssl://"):
                    return "https://" + decoded[6:]
                if decoded.startswith("ssl:"):
                    return "https://" + decoded[4:]
                return decoded
        except Exception:
            pass
    return url


def _pixel_hash(url: str) -> str | None:
    """Télécharge une image, la normalise en 64×64 RGBA, retourne le MD5 des pixels."""
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        # Ne pas rejeter les 404 : certains CDN retournent une image placeholder avec ce code
        img = Image.open(io.BytesIO(r.content)).convert("RGBA").resize(_NORM, Image.LANCZOS)
        return hashlib.md5(img.tobytes()).hexdigest()
    except Exception:
        return None


def _load_ref_hashes() -> dict[str, set[str]]:
    """Calcule les hash de référence pour chaque marchand configuré."""
    refs: dict[str, set[str]] = {}
    for merchant, urls in PLACEHOLDER_REF_URLS.items():
        for url in urls:
            h = _pixel_hash(url)
            if h:
                refs.setdefault(merchant, set()).add(h)
                print(f"  📌 Référence [{merchant}] hash={h[:10]}…")
            else:
                print(f"  ⚠️  Impossible de charger la référence [{merchant}]: {url[:70]}")
    return refs


def _fetch_products() -> list[dict]:
    PAGE, rows, offset = 1000, [], 0
    while True:
        page = (
            _client.table("products")
            .select("id,name,brand,price,affiliate_url,image_url,merchant_key")
            .eq("active", True)
            .order("merchant_key")
            .range(offset, offset + PAGE - 1)
            .execute()
            .data or []
        )
        rows.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
    return rows


def _check_one(p: dict, refs: dict[str, set[str]]) -> dict:
    """Vérifie si l'image d'un produit est un placeholder (par comparaison pixel)."""
    img_url  = p.get("image_url") or ""
    merchant = p.get("merchant_key") or ""

    if not img_url:
        return {**p, "_status": "nourl"}

    merchant_refs = refs.get(merchant)
    if merchant_refs is None:
        return {**p, "_status": "unknown"}

    # Résoudre le proxy productserve → URL CDN directe, même niveau que la référence
    resolved = _resolve_image_url(img_url)
    h = _pixel_hash(resolved)
    if h is None:
        h = _pixel_hash(img_url)  # fallback: URL brute
    if h is None:
        return {**p, "_status": "error"}

    return {**p, "_status": "placeholder" if h in merchant_refs else "ok"}


# ── HTML ──────────────────────────────────────────────────────────────────────

_HTML_HEAD = """\
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Images produits — {date}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:system-ui,sans-serif;font-size:13px;background:#f5f5f5;color:#222}}
  h1{{padding:16px 20px;background:#1a1a2e;color:#fff;font-size:16px}}
  h1 span{{font-weight:400;opacity:.7;font-size:13px;margin-left:12px}}
  .stats{{display:flex;gap:10px;padding:12px 20px;background:#fff;border-bottom:1px solid #e0e0e0;flex-wrap:wrap}}
  .stat{{padding:5px 14px;border-radius:20px;font-size:12px;font-weight:600}}
  .s-ok{{background:#d4edda;color:#155724}}
  .s-ph{{background:#fef08a;color:#713f12}}
  .s-nourl{{background:#f8d7da;color:#721c24}}
  .s-unk{{background:#e2e8f0;color:#475569}}
  .s-err{{background:#fde8d8;color:#9a3412}}
  table{{width:100%;border-collapse:collapse}}
  th{{position:sticky;top:0;background:#1a1a2e;color:#fff;padding:8px 10px;text-align:left;font-size:12px;z-index:2}}
  tr:nth-child(even){{background:#fafafa}}
  tr:hover{{background:#f0f4ff}}
  tr.r-ph{{background:#fffbeb!important}}
  td{{padding:8px 10px;border-bottom:1px solid #eee;vertical-align:middle}}
  td.ic{{width:84px;text-align:center}}
  td.ic img{{width:72px;height:72px;object-fit:contain;background:#fff;border:1px solid #ddd;border-radius:6px;display:block;margin:auto}}
  td.ic .ni{{width:72px;height:72px;background:#f0f0f0;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:18px;margin:auto;color:#aaa}}
  .lbl{{margin-top:4px;font-size:10px;font-weight:700;border-radius:8px;padding:1px 6px;display:inline-block}}
  .l-ok{{background:#d4edda;color:#155724}}
  .l-ph{{background:#fef08a;color:#713f12}}
  .l-nourl{{background:#f8d7da;color:#721c24}}
  .l-unk{{background:#e2e8f0;color:#475569}}
  .l-err{{background:#fde8d8;color:#9a3412}}
  .name{{font-weight:600;max-width:260px}}
  .brand{{color:#666;font-size:11px}}
  .price{{font-weight:700;color:#e44;white-space:nowrap}}
  .merch{{font-size:11px;color:#888}}
  a{{color:#2563eb;text-decoration:none}}
  a:hover{{text-decoration:underline}}
</style>
</head>
<body>
<h1>Images produits<span>{count} produits — {date}</span></h1>
<div class="stats">
  <span class="stat s-ok">✅ OK : {n_ok}</span>
  <span class="stat s-ph">🖼 Placeholder : {n_ph}</span>
  <span class="stat s-nourl">— Sans image : {n_nourl}</span>
  <span class="stat s-unk">? Non vérifié : {n_unk}</span>
  <span class="stat s-err">⚠ Erreur chargement : {n_err}</span>
</div>
<table>
<thead><tr>
  <th>#</th><th>Image</th><th>Produit</th><th>Marchand</th><th>Prix</th><th>Lien affilié</th>
</tr></thead>
<tbody>
"""

_HTML_FOOT = "</tbody></table></body></html>\n"

_STATUS_MAP = {
    "ok":          ("l-ok",    "✓ Image"),
    "placeholder": ("l-ph",    "🖼 Placeholder"),
    "nourl":       ("l-nourl", "— pas d'URL"),
    "unknown":     ("l-unk",   "? non vérifié"),
    "error":       ("l-err",   "⚠ erreur"),
}


def _img_tag(image_url: str) -> str:
    if not image_url:
        return '<div class="ni">📷</div>'
    # Résoudre le proxy productserve → URL CDN directe pour affichage dans le navigateur
    display_url = _resolve_image_url(image_url)
    esc = html_mod.escape(display_url)
    return f'<img src="{esc}" alt="" loading="lazy" onerror="this.style.opacity=\'0.15\'">'


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"\n{'═'*62}")
    print(f"  🖼  check_affiliate_links.py — détection placeholder (pixels)")
    print(f"{'═'*62}\n")

    # 1. Charger les hash de référence
    print("  Chargement des images de référence…")
    refs = _load_ref_hashes()
    checked_merchants = set(refs.keys())
    print(f"  → {len(refs)} marchand(s) avec référence : {', '.join(checked_merchants) or '—'}\n")

    # 2. Récupérer les produits
    print("  Récupération des produits actifs depuis Supabase…")
    products = _fetch_products()
    if not products:
        print("❌ Aucun produit trouvé.")
        return 1
    print(f"  → {len(products)} produits\n")

    # 3. Vérification parallèle des images
    results: list[dict] = []
    n_ok = n_ph = n_nourl = n_unk = n_err = 0

    # Séparer les produits à vérifier (avec référence) des autres
    to_check  = [p for p in products if p.get("merchant_key") in checked_merchants and p.get("image_url")]
    no_check  = [p for p in products if p not in to_check]

    # Les produits sans merchant référencé sont marqués directement
    for p in no_check:
        if p.get("image_url"):
            results.append({**p, "_status": "unknown"})
            n_unk += 1
        else:
            results.append({**p, "_status": "nourl"})
            n_nourl += 1

    print(f"  Vérification de {len(to_check)} images ({len(no_check)} non vérifiables)…")
    done = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(_check_one, p, refs): p for p in to_check}
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            results.append(r)
            st = r["_status"]
            if st == "ok":          n_ok  += 1
            elif st == "placeholder": n_ph  += 1
            elif st == "error":     n_err += 1
            if done % 20 == 0 or done == len(to_check):
                print(f"  … {done}/{len(to_check)}", end="\r")

    print()
    print(f"\n  ✅ OK : {n_ok}  |  🖼 Placeholder : {n_ph}  |  — Sans image : {n_nourl}  |  ? Non vérifié : {n_unk}  |  ⚠ Erreur : {n_err}\n")

    # 4. Générer le HTML
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Trier : placeholders en premier, puis erreurs, puis OK, puis non vérifiés
    _order = {"placeholder": 0, "error": 1, "nourl": 2, "ok": 3, "unknown": 4}
    results.sort(key=lambda p: (_order.get(p["_status"], 9), p.get("merchant_key") or ""))

    with OUTPUT_HTML.open("w", encoding="utf-8") as f:
        f.write(_HTML_HEAD.format(
            date=date_str, count=len(products),
            n_ok=n_ok, n_ph=n_ph, n_nourl=n_nourl, n_unk=n_unk, n_err=n_err,
        ))
        for i, p in enumerate(results, 1):
            st  = p["_status"]
            lbl_cls, lbl_txt = _STATUS_MAP.get(st, ("l-unk", st))
            img_url = p.get("image_url") or ""
            aff_url = html_mod.escape(p.get("affiliate_url") or "#")
            row_cls = ' class="r-ph"' if st == "placeholder" else ""
            f.write(
                f'<tr{row_cls}>\n'
                f'  <td style="color:#aaa;width:36px">{i}</td>\n'
                f'  <td class="ic">{_img_tag(img_url)}'
                f'<span class="lbl {lbl_cls}">{lbl_txt}</span></td>\n'
                f'  <td><div class="name">{html_mod.escape((p.get("name") or "?")[:80])}</div>'
                f'<div class="brand">{html_mod.escape(p.get("brand") or "")}</div></td>\n'
                f'  <td class="merch">{html_mod.escape(p.get("merchant_key") or "")}</td>\n'
                f'  <td class="price">{"" + str(p["price"]) + " €" if p.get("price") else "—"}</td>\n'
                f'  <td><a href="{aff_url}" target="_blank" rel="noopener">Ouvrir ↗</a></td>\n'
                f'</tr>\n'
            )
        f.write(_HTML_FOOT)

    print(f"  📄 {OUTPUT_HTML}")
    print(f"\n  👉 open \"{OUTPUT_HTML}\"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

