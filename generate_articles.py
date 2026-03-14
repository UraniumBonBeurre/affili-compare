#!/usr/bin/env python3
"""
generate_articles.py — Génère des articles + visuels Pinterest, sauvegarde locale
===================================================================================

Pour chaque article généré, crée un dossier :
  output/articles/{slug}/
    article_fr.html        — article standalone (même rendu que le site, CSS embarqué)
    article_en.html
    pins/
      pin_fr_1.jpg         — visuels Pinterest par variante et langue
      pin_en_1.jpg
      pin_fr_2.jpg
      pin_en_2.jpg
    pin.txt                — titre, description, lien externe (par langue)

Options obligatoires :
  --count INT              Nombre d'articles à générer
  --nb_produits INT        Nombre de produits par article
  --nb_variantes_pins INT  Nombre de variantes de pin par langue par article
  --publish {local,pinterest}  Destination (défaut: local)
  --placeholder {true,false}   Utiliser une image placeholder pour le fond des pins (défaut: true)

Exemples :
    python3 generate_articles.py --count 2 --nb_produits 5 --nb_variantes_pins 2
    python3 generate_articles.py --count 1 --nb_produits 8 --nb_variantes_pins 3 --publish pinterest
    python3 generate_articles.py --count 1 --nb_produits 5 --nb_variantes_pins 2 --placeholder false
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Réutilise toutes les fonctions du module principal ───────────────────────
import create_and_post_top_products as cap
from settings import (
    ROOT, SITE_URL,
    nb_products_per_article, nb_pins_per_article,
    check_supabase, get_board_for_niche,
)

# ── Dossier de sortie ─────────────────────────────────────────────────────────
ARTICLES_OUT = ROOT / "output" / "articles"

# ── CSS standalone embarqué (reproduit le rendu du site) ─────────────────────
_ARTICLE_CSS = """
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #fafaf9;
    color: #292524;
    padding: 2rem 1rem;
  }
  .article-wrapper {
    max-width: 56rem;
    margin: 0 auto;
    background: #fff;
    border-radius: 1rem;
    padding: 2rem 2.5rem;
    box-shadow: 0 1px 3px rgba(0,0,0,.08);
  }
  .article-meta {
    font-size: .8rem;
    color: #a8a29e;
    margin-bottom: .5rem;
    text-transform: uppercase;
    letter-spacing: .05em;
  }
  h1.article-title {
    font-size: 1.75rem;
    font-weight: 700;
    color: #1c1917;
    line-height: 1.25;
    margin-bottom: 1rem;
  }
  .article-intro {
    font-size: 1.05rem;
    line-height: 1.7;
    color: #57534e;
    margin-bottom: 2rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid #e7e5e4;
  }
  /* Article body */
  .article-body p { margin-bottom: 1rem; line-height: 1.7; }
  .article-body h3 { font-size: 1.1rem; font-weight: 700; color: #1c1917; margin: 1.5rem 0 .5rem; }
  .article-body strong { color: #1c1917; font-weight: 600; }
  .article-body em { font-style: italic; color: #78716c; }
  .article-body a {
    color: #b45309;
    text-decoration: underline;
    text-underline-offset: 2px;
    font-weight: 500;
  }
  .article-body a:hover { color: #78350f; }
  /* Quinconce layout */
  .product-block {
    display: flex;
    gap: 1.25rem;
    margin: 1.75rem 0;
    align-items: flex-start;
  }
  .product-block-left  { flex-direction: row; }
  .product-block-right { flex-direction: row-reverse; }
  .product-block-noimg { display: block; margin: 1.25rem 0; }
  .product-block-media {
    flex: none;
    width: 160px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: .5rem;
  }
  .product-block-media {
    flex: none;
    width: 160px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: .5rem;
  }
  .product-block-img {
    width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: contain;
    background: #fff;
    border-radius: .75rem;
    border: 1px solid #e7e5e4;
    box-shadow: 0 1px 2px rgba(0,0,0,.06);
    padding: .375rem;
  }
  .product-block-cta {
    display: inline-block;
    font-size: .7rem;
    background: #d97706;
    color: #fff;
    padding: .25rem .75rem;
    border-radius: .5rem;
    font-weight: 700;
    text-decoration: none;
    margin-top: .5rem;
  }
  .product-block-cta:hover { background: #b45309; }
  .product-block-text { flex: 1; min-width: 0; }
  .product-block-text p { color: #44403c; line-height: 1.65; }
  @media (max-width: 640px) {
    .product-block { flex-direction: column !important; }
    .product-block-media { width: 100%; max-width: 180px; margin: 0 auto; }
    .article-wrapper { padding: 1.25rem; }
  }
"""


def _build_standalone_html(
        title: str,
        intro: str,
        body_html: str,
        niche_label: str,
        month: str,
        lang: str,
) -> str:
    """Construit une page HTML standalone complète qui reproduit le rendu du site."""
    lang_attr = lang  # "fr" ou "en"
    now_str = datetime.now().strftime("%d/%m/%Y")
    # Les fichiers file:// bloquent target="_blank" comme popup → about:blank.
    # On retire l'attribut pour que les liens s'ouvrent normalement dans l'onglet courant.
    body_html = re.sub(r'\s+target="_blank"', '', body_html)
    return f"""<!DOCTYPE html>
<html lang="{lang_attr}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>{_ARTICLE_CSS}</style>
</head>
<body>
  <div class="article-wrapper">
    <p class="article-meta">{niche_label} · {month} · généré le {now_str}</p>
    <h1 class="article-title">{title}</h1>
    <div class="article-intro">{intro}</div>
    <div class="article-body">
{body_html}
    </div>
  </div>
</body>
</html>"""


def _write_pin_txt(
        out_dir: Path,
        pin_content: dict,
        article_url: str,
        products: list,
) -> None:
    """Écrit pin.txt avec titre, description et lien externe (FR + EN) pour chaque variante."""
    fr = pin_content.get("fr", {})
    en = pin_content.get("en", {})
    lines = [
        "═══════════════════════════════════════════════════════════",
        "  PIN — Contenu Pinterest",
        "═══════════════════════════════════════════════════════════",
        "",
        "── FRANÇAIS ────────────────────────────────────────────────",
        f"TITRE       : {fr.get('pin_title', '')}",
        f"OVERLAY     : {fr.get('overlay_hero', '')}",
        "",
        "DESCRIPTION :",
        fr.get("description", ""),
        "",
        "── ENGLISH ─────────────────────────────────────────────────",
        f"TITLE       : {en.get('pin_title', '')}",
        f"OVERLAY     : {en.get('overlay_hero', '')}",
        "",
        "DESCRIPTION :",
        en.get("description", ""),
        "",
        "═══════════════════════════════════════════════════════════",
        f"LIEN ARTICLE  : {article_url}",
        "",
        "── LIENS AFFILIÉS ──────────────────────────────────────────",
    ]
    for p in products:
        aff = p.get("affiliate_url") or p.get("url") or "#"
        name = (p.get("name") or "?").strip()[:60]
        brand = (p.get("brand") or "").strip()
        price = p.get("price") or "?"
        lines.append(f"  {name} ({brand}, {price} €) → {aff}")
    lines.append("")
    (out_dir / "pin.txt").write_text("\n".join(lines), encoding="utf-8")


def run_article(
        niche: str,
        taxonomy: dict,
        trends: dict,
        args: argparse.Namespace,
        angle: str = "selection",
) -> bool:
    year, mo = args.month.split("-")
    month_fr = cap.MONTH_FR.get(mo, mo)
    niche_cfg = taxonomy.get("niche_config", {}).get(niche, {})
    niche_label    = niche_cfg.get("label_fr", niche.replace("_", " "))
    niche_label_en = niche_cfg.get("label_en") or cap._NICHE_LABEL_EN.get(niche, niche.replace("_", " ").title())
    slug_prefix    = niche_cfg.get("page_slug_prefix", niche.replace("_", "-"))
    slug = f"{slug_prefix}-{args.month}"
    article_url = f"{SITE_URL}/top/{slug}"

    print(f"\n  🔍 Niche : {niche}  ({niche_label})  — angle : {angle}")

    # 1. Produits
    products = cap.fetch_diverse_products(niche, count=args.nb_produits, taxonomy=taxonomy)
    if len(products) < min(3, args.nb_produits):
        print(f"  ⚠️  Seulement {len(products)} produits — article ignoré")
        return False

    # 2. Contenu LLM
    content = cap.generate_content(niche, niche_label, month_fr, year, products, taxonomy, angle=angle)
    print(f"  📝 Titre FR : {content['title']}")
    print(f"  📝 Titre EN : {content.get('title_en', '')}")

    # 3. Contenu Pinterest
    pin_content = cap.generate_pin_content(
        content["title"], niche_label, args.nb_produits, products, month_fr, year
    )
    print(f"  📌 Pin title FR : {pin_content['fr']['pin_title']}")
    print(f"  📌 Pin title EN : {pin_content['en']['pin_title']}")

    # 4. Dossier de sortie
    slug_safe = re.sub(r"[^a-z0-9-]", "", slug.lower())[:55]
    out_dir = ARTICLES_OUT / slug_safe
    pins_dir = out_dir / "pins"
    pins_dir.mkdir(parents=True, exist_ok=True)

    # 5. Sauvegarder les articles HTML
    html_fr = _build_standalone_html(
        title=content["title"],
        intro=content["intro"],
        body_html=content.get("body_html_fr", ""),
        niche_label=niche_label,
        month=args.month,
        lang="fr",
    )
    html_en = _build_standalone_html(
        title=content.get("title_en", content["title"]),
        intro=content.get("intro_en", content["intro"]),
        body_html=content.get("body_html_en", ""),
        niche_label=niche_label_en,
        month=args.month,
        lang="en",
    )
    (out_dir / "article_fr.html").write_text(html_fr, encoding="utf-8")
    (out_dir / "article_en.html").write_text(html_en, encoding="utf-8")
    print(f"  📄 article_fr.html + article_en.html → {out_dir}")

    # 6. Visuels Pinterest
    board_name_fr, board_id_fr = get_board_for_niche(niche, "fr")
    board_name_en, board_id_en = get_board_for_niche(niche, "en")

    nb_vis = max(1, min(args.nb_variantes_pins, 3))
    print(f"\n  🎨 Génération de {nb_vis} variante(s) × 2 langues…")

    # Contrôle du mode placeholder : on adapte production_workflow du module
    # False → utilise placeholder.jpg  |  True → appelle HF FLUX
    _orig_pw = cap.production_workflow
    cap.production_workflow = not args.placeholder  # False si --placeholder true

    _top_p_fr = f"Top {args.nb_produits} {niche_label}"
    _top_p_en = f"Top {args.nb_produits} {niche_label_en}"
    _ov_fr_pool = [
        pin_content["fr"]["overlay_hero"],
        content["title"][:55] if len(content["title"]) <= 55 else _top_p_fr,
        _top_p_fr,
    ]
    _ov_en_pool = [
        pin_content["en"]["overlay_hero"],
        content.get("title_en", "")[:55] or _top_p_en,
        _top_p_en,
    ]

    # generate_visuals() écrit dans public/local_pins/{slug}/
    # On récupère les chemins et on les copie dans notre dossier output/articles/
    pin_paths = cap.generate_visuals(
        slug, content["title"], args.nb_produits, niche, niche_label,
        month_fr, year, products, taxonomy, nb_vis,
        overlay_texts_fr=_ov_fr_pool[:nb_vis],
        overlay_texts_en=_ov_en_pool[:nb_vis],
        board_name_fr=board_name_fr,
        board_name_en=board_name_en,
    )

    # Restaurer production_workflow
    cap.production_workflow = _orig_pw

    # Copier les visuels générés dans output/articles/{slug}/pins/
    import shutil
    copied_fr, copied_en = [], []
    for i, src_path in enumerate(pin_paths.get("fr", []), 1):
        dst = pins_dir / f"pin_fr_{i}.jpg"
        shutil.copy2(src_path, dst)
        copied_fr.append(str(dst))
        print(f"     → [FR] pin_fr_{i}.jpg")
    for i, src_path in enumerate(pin_paths.get("en", []), 1):
        dst = pins_dir / f"pin_en_{i}.jpg"
        shutil.copy2(src_path, dst)
        copied_en.append(str(dst))
        print(f"     → [EN] pin_en_{i}.jpg")

    local_pin_paths = {"fr": copied_fr, "en": copied_en}

    # 7. pin.txt
    _write_pin_txt(out_dir, pin_content, article_url, products)
    print(f"  📝 pin.txt → {out_dir / 'pin.txt'}")

    # 8. Publication Pinterest (si demandée)
    if args.publish == "pinterest":
        print(f"\n  📌 Publication Pinterest…")
        cap.publish_visuals_pinterest(
            slug, content["title"], niche, niche_label, args.month,
            pin_paths=local_pin_paths,
            taxonomy=taxonomy,
            pin_title=pin_content["fr"]["pin_title"],
            pin_description=pin_content["fr"]["description"],
            board_id_fr=board_id_fr,
            board_id_en=board_id_en,
            pin_content=pin_content,
            publish_to_pinterest=True,
        )
    else:
        print(f"  💾 Sauvegarde locale uniquement (--publish local)")

    print(f"\n  ✅ Article prêt → {out_dir}")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Génère des articles Top N + visuels Pinterest (sauvegarde locale ou publication)"
    )
    parser.add_argument("--count", type=int, default=1,
                        help="Nombre d'articles à générer (défaut: 1)")
    parser.add_argument("--nb_produits", type=int, default=nb_products_per_article,
                        help=f"Nombre de produits par article (défaut: {nb_products_per_article})")
    parser.add_argument("--nb_variantes_pins", type=int, default=nb_pins_per_article,
                        help=f"Nombre de variantes de pin par langue par article (défaut: {nb_pins_per_article}, max 3)")
    parser.add_argument("--publish", choices=["local", "pinterest"], default="local",
                        help="Destination des pins : local (défaut) ou pinterest")
    parser.add_argument("--placeholder", type=lambda v: v.lower() != "false", default=True,
                        metavar="{true,false}",
                        help="Utiliser un placeholder pour le fond des pins (défaut: true)")
    parser.add_argument("--niche", default=None,
                        help="Forcer une niche spécifique (optionnel)")
    parser.add_argument("--angle", choices=cap.ARTICLE_ANGLES, default=None,
                        help="Angle éditorial forcé : selection, guide_achat, budget_premium, profil_acheteur")
    parser.add_argument("--month", default=None,
                        help="Mois cible YYYY-MM (défaut: mois courant)")
    parser.add_argument("--no-trends", action="store_true",
                        help="Ignorer les tendances Pinterest")
    args = parser.parse_args()

    if not args.month:
        args.month = datetime.now().strftime("%Y-%m")

    check_supabase()

    img_mode = "placeholder" if args.placeholder else "HF FLUX.1-schnell"
    print(f"\n{'═'*65}")
    print(f"  📰  generate_articles.py")
    print(f"  Articles    : {args.count}")
    print(f"  Produits    : {args.nb_produits} par article")
    print(f"  Pins        : {args.nb_variantes_pins} variante(s) × 2 langues")
    print(f"  Publication : {args.publish}")
    print(f"  Fond pins   : {img_mode}")
    print(f"  Mois        : {args.month}")
    print(f"  Sortie      : {ARTICLES_OUT}")
    print(f"{'═'*65}\n")

    taxonomy = cap._load_taxonomy()

    print("📊 Comptage des produits par niche…")
    niche_counts = cap._niche_product_counts(taxonomy)

    trends = {}
    if not args.no_trends:
        print("📈 Récupération des tendances Pinterest…")
        trends = cap.fetch_pinterest_trends()

    ARTICLES_OUT.mkdir(parents=True, exist_ok=True)

    total = ok = 0
    used_niches: set = set()
    max_attempts = args.count * 5

    for attempt in range(1, max_attempts + 1):
        if ok >= args.count:
            break

        forced = args.niche if attempt == 1 else None
        print(f"\n{'─'*65}")
        print(f"  [Article {ok+1}/{args.count}] Tentative {attempt}/{max_attempts}")
        niche = cap.pick_niche(
            taxonomy, trends,
            forced=forced,
            exclude=used_niches,
            niche_counts=niche_counts,
            min_products=min(3, args.nb_produits),
        )
        used_niches.add(niche)
        total += 1
        angle = args.angle if args.angle else cap.pick_angle(niche, taxonomy)

        success = run_article(niche, taxonomy, trends, args, angle=angle)
        if success:
            ok += 1
            taxonomy.setdefault("last_used",  {})[niche] = datetime.now().isoformat()
            taxonomy.setdefault("last_angle", {})[niche] = angle
            cap._save_taxonomy(taxonomy)

        if ok < args.count and attempt < max_attempts:
            time.sleep(5)

    print(f"\n{'═'*65}")
    print(f"  ✅  {ok}/{total} article(s) générés")
    print(f"  📁  Dossier de sortie : {ARTICLES_OUT}")
    print(f"{'═'*65}\n")


if __name__ == "__main__":
    main()
