#!/usr/bin/env python3
"""
test_pin_creation.py — Test complet génération pins sur 3 niches hardcodées
=============================================================================

Pour chaque niche, le script :
  1. Récupère de vrais produits depuis Supabase
  2. Affiche en clair tout ce qui est envoyé aux LLMs
  3. Génère : titre article, intro, titre pin, description+hashtags, overlay
  4. Génère les images hero + spotlight
  5. Sauvegarde dans tests/output/{niche}/ :
       article.txt   → titre, intro, liste produits
       pin.txt       → titre pin, description, overlay, URL
       hero.jpg      + spotlight.jpg (avec overlay)

Usage :
    python tests/test_pin_creation.py
    python tests/test_pin_creation.py --no-image
    python tests/test_pin_creation.py --pin-only
    python tests/test_pin_creation.py --niches mobile_nomade smart_home
    python tests/test_pin_creation.py --month 2026-07
    python tests/test_pin_creation.py --nb-products 7
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Setup path pour importer settings ──────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests

from settings import (
    SUPABASE_URL, SUPABASE_KEY, TAXONOMY_PATH, BOARDS_PATH, FONTS_DIR, OUTPUT_DIR,
    OLLAMA_CLOUD_API_KEY, OLLAMA_CLOUD_HOST, OLLAMA_CLOUD_MODEL, OLLAMA_CLOUD_PINS_MODEL,
    HF_API_TOKEN, SITE_URL,
    sb_headers, get_board_for_niche,
)

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    _PIL = True
except ImportError:
    _PIL = False

# ── Constantes ─────────────────────────────────────────────────────────────────
PIN_W, PIN_H = 1000, 1500

MONTH_FR = {
    "01": "janvier", "02": "février",   "03": "mars",    "04": "avril",
    "05": "mai",     "06": "juin",      "07": "juillet", "08": "août",
    "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre",
}

# 3 niches hardcodées pour le test (différentes du run précédent)
DEFAULT_TEST_NICHES = ["home_office_setup", "bathroom_storage", "outdoor_living"]

TEST_OUTPUT = ROOT / "tests" / "output"


# ═══════════════════════════════════════════════════════════════════════════════
# LLM
# ═══════════════════════════════════════════════════════════════════════════════

def call_llm(prompt: str, max_tokens: int = 400, model: str = None) -> str | None:
    if not OLLAMA_CLOUD_API_KEY:
        print("❌ OLLAMA_CLOUD_API_KEY manquant")
        return None
    _model = model or OLLAMA_CLOUD_MODEL
    for attempt in range(3):
        try:
            r = requests.post(
                f"{OLLAMA_CLOUD_HOST}/api/chat",
                headers={"Authorization": f"Bearer {OLLAMA_CLOUD_API_KEY}",
                         "Content-Type": "application/json"},
                json={"model": _model,
                      "messages": [{"role": "user", "content": prompt}],
                      "stream": False,
                      "think": False,
                      "options": {"temperature": 0.65, "num_predict": max_tokens}},
                timeout=90,
            )
            if r.status_code == 429:
                time.sleep(12 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            if os.getenv("DEBUG_LLM"):
                import json as _j
                print(f"  [DEBUG] done_reason={data.get('done_reason')}, "
                      f"eval_count={data.get('eval_count')}, "
                      f"content_len={len(data.get('message',{}).get('content',''))}")
            text = data["message"]["content"].strip()
            text = re.sub(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+", "", text).strip()
            return text
        except Exception as e:
            if attempt < 2:
                time.sleep(8)
            else:
                print(f"  ⚠️  LLM échec: {e}")
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# PRODUITS RÉELS (Supabase)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_products_for_niche(niche: str, taxonomy: dict, count: int = 5) -> list:
    """Récupère de vrais produits depuis Supabase pour la niche."""
    select = "id,name,brand,image_url,price,currency,llm_product_type,affiliate_url"
    url = (f"{SUPABASE_URL}/rest/v1/products?"
           f"llm_niches=cs.{{{niche}}}&active=not.is.false"
           f"&select={select}&order=price.asc.nullslast&limit={count * 10}")
    try:
        r = requests.get(url, headers=sb_headers(), timeout=15)
        r.raise_for_status()
        rows = r.json()
    except Exception as e:
        print(f"  ⚠️  Supabase: {e}")
        return []

    # Diversification par product_type
    seen_types, products = set(), []
    for row in rows:
        if len(products) >= count:
            break
        pt = row.get("llm_product_type") or ""
        if pt and pt in seen_types:
            continue
        if not (row.get("affiliate_url") or row.get("price")):
            continue
        if pt:
            seen_types.add(pt)
        products.append(row)
    return products


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITAIRE
# ═══════════════════════════════════════════════════════════════════════════════

def _slugify(text: str) -> str:
    """Slug ASCII simple pour les balises PRODUCT_IMAGE."""
    text = text.lower()
    for src, dst in [("éèêë", "e"), ("àâä", "a"), ("ùûü", "u"), ("ôö", "o"), ("îï", "i"), ("ç", "c")]:
        for c in src:
            text = text.replace(c, dst)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:45]


# ═══════════════════════════════════════════════════════════════════════════════
# GÉNÉRATION CORPS DE L'ARTICLE
# Titre = overlay pin_01 (passé en argument)
# Corps = présentation de chaque produit avec liens affiliés + balises images
# ═══════════════════════════════════════════════════════════════════════════════

def generate_article_body(article_title_fr: str, article_title_en: str, products: list,
                          niche_label: str, month_fr: str, year: str) -> tuple[str, str, str]:
    """Génère le corps Markdown de l'article en FR ET EN dans un seul appel LLM.
    Retourne (fr_body, en_body, prompt)."""
    # Préparer le bloc produits avec slugs et liens pré-calculés
    prod_blocks = []
    for i, p in enumerate(products, 1):
        name  = (p.get("name")  or "?").strip()
        brand = (p.get("brand") or "?").strip()
        price = p.get("price") or "?"
        url   = p.get("affiliate_url") or ""
        slug  = _slugify(f"{brand}-{name[:35]}")
        link_md_fr = f"[{name}]({url})" if url else name
        link_md_en = link_md_fr  # same URL, same name (product names stay as-is)
        prod_blocks.append(
            f"{i}. {name} — {brand} — {price} €\n"
            f"   Balise image  : {{{{PRODUCT_IMAGE:{slug}}}}}\n"
            f"   Lien Markdown : {link_md_fr}"
        )
    products_block = "\n\n".join(prod_blocks)

    prompt = f"""Tu rédiges le corps d'un article de blog d'affiliation en DEUX langues : français ET anglais.

Titre FR de l'article : « {article_title_fr} »
Titre EN de l'article : « {article_title_en} »
Thème : {niche_label} — {month_fr} {year}

{len(products)} PRODUITS À PRÉSENTER (dans cet ordre) :

{products_block}

STRUCTURE ATTENDUE (pour chaque langue) :
1. Accroche courte (2-3 phrases) — ton direct, chaleureux, donne envie de lire.
2. Pour CHAQUE produit, dans l'ordre :
   a. La balise image sur sa propre ligne (copie-la exactement telle que fournie — IDENTIQUE en FR et EN)
   b. Un paragraphe de 3-5 phrases dans la langue cible.
      Dans ce paragraphe, cite le nom du produit avec le lien Markdown exact fourni.
3. Conclusion courte (2-3 phrases) + CTA.

RÈGLES ABSOLUES :
- Copie les balises {{{{PRODUCT_IMAGE:...}}}} EXACTEMENT telles qu'elles sont fournies, identiques en FR et EN.
- Utilise les liens Markdown EXACTS fournis pour chaque produit.
- Ton : blog lifestyle, direct, chaleureux.
- 300 à 450 mots par langue.
- PAS de titre Markdown (#) — juste le corps du texte.
- Retourne EXACTEMENT ce format, rien d'autre :

[corps en français ici — 300-450 mots]
===ENGLISH===
[english body here — 300-450 words]"""

    print(f"\n{'─'*60}")
    print(f"  📝 PROMPT CORPS ARTICLE BILINGUE (ARTICLES_WRITING_LLM : {OLLAMA_CLOUD_MODEL}) :")
    print(f"{'─'*60}")
    print(prompt)
    print(f"{'─'*60}\n")

    raw = call_llm(prompt, 3000) or ""
    parts = raw.split("===ENGLISH===", 1)
    fr_body = parts[0].strip() if parts else ""
    en_body = parts[1].strip() if len(parts) == 2 else ""

    def _fallback_body(lang: str, title: str) -> str:
        paras = [f"{'Découvrez' if lang == 'fr' else 'Discover'} notre sélection {niche_label} de {month_fr} {year}.\n"
                 if lang == 'fr' else
                 f"Discover our {niche_label} selection for {month_fr} {year}.\n"]
        for p in products:
            name  = (p.get("name") or "?").strip()
            brand = (p.get("brand") or "?").strip()
            price = p.get("price") or "?"
            url   = p.get("affiliate_url") or ""
            slug  = _slugify(f"{brand}-{name[:35]}")
            link  = f"[{name}]({url})" if url else name
            paras.append(f"{{{{PRODUCT_IMAGE:{slug}}}}}\n{link} ({brand}, {price} €) {'fait partie de nos coups de cœur.' if lang == 'fr' else 'is one of our top picks.'}\n")
        paras.append(f"{'Retrouvez toute la sélection sur' if lang == 'fr' else 'See the full selection on'} [MyGoodPick]({SITE_URL}).")
        return "\n\n".join(paras)

    if not fr_body or len(fr_body.split()) < 50:
        fr_body = _fallback_body("fr", article_title_fr)
    if not en_body or len(en_body.split()) < 50:
        en_body = _fallback_body("en", article_title_en)

    return fr_body, en_body, prompt


# ═══════════════════════════════════════════════════════════════════════════════
# GÉNÉRATION CONTENU PIN (titre pin, description+hashtags, overlay)
# Via PINS_WRITING_LLM
# ═══════════════════════════════════════════════════════════════════════════════

def generate_pin_content(title: str, n: int, niche_label: str,
                         product_list: str, month_fr: str, year: str,
                         variation_num: int = 1, nb_variations: int = 1) -> dict:
    """Génère le contenu PIN en FR et EN via un seul appel LLM (JSON structuré).
    Retourne dict avec clés 'fr', 'en' (chacun: pin_title, description, overlay_hero) + '_prompts'."""

    variation_hint = (
        f"\nATTENTION — Variation {variation_num}/{nb_variations} : "
        f"angle et formulation COMPLÈTEMENT DIFFÉRENTS des autres variations.\n"
    ) if nb_variations > 1 else ""

    prompt = f"""Tu génères du contenu Pinterest en FRANÇAIS et en ANGLAIS pour une épingle.
{variation_hint}
Thème : {niche_label} — {n} produits — {month_fr} {year}
Produits : {product_list}

Retourne UNIQUEMENT un objet JSON valide avec cette structure exacte (aucun texte avant ou après) :
{{
  "fr": {{
    "pin_title": "Titre pin en français (50-100 car, accrocheur, crée une émotion, NE PAS commencer par Top)",
    "overlay_hero": "Texte overlay en français (5 à 10 mots, percutant, direct)",
    "description": "Description Pinterest FR : accroche 1 phrase + 2-3 phrases bénéfices + CTA + 6-8 hashtags FR sur une ligne"
  }},
  "en": {{
    "pin_title": "Pin title in English (50-100 chars, engaging, emotion-driven, DO NOT start with Top)",
    "overlay_hero": "Overlay text in English (5 to 10 words, punchy, direct)",
    "description": "Pinterest description EN: 1-sentence hook + 2-3 benefit sentences + CTA + 6-8 English hashtags on one line"
  }}
}}

RÈGLES pin_title : différent de l'overlay, ton émotionnel/FOMO, chiffre {n} si possible.
RÈGLES overlay_hero : ultra-court (5-10 mots), affiché en TRÈS GROS sur l'image, crée une envie immédiate.
RÈGLES description : 200-350 caractères hors hashtags, ton chaleureux, hashtags thématiques + saisonniers."""

    print(f"\n{'─'*60}")
    var_label = f" [variation {variation_num}/{nb_variations}]" if nb_variations > 1 else ""
    print(f"  📌 PROMPT PIN BILINGUE{var_label} (PINS_WRITING_LLM : {OLLAMA_CLOUD_PINS_MODEL}) :")
    print(f"{'─'*60}")
    print(prompt)
    print(f"{'─'*60}\n")

    raw = call_llm(prompt, 1000, model=OLLAMA_CLOUD_PINS_MODEL) or ""

    # Parse JSON avec fallback
    fr_data: dict = {}
    en_data: dict = {}
    try:
        cleaned = re.sub(r"```json\s*|\s*```", "", raw).strip()
        # Sometimes LLM adds a leading/trailing comment before JSON
        json_start = cleaned.find("{")
        json_end = cleaned.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            cleaned = cleaned[json_start:json_end]
        d = json.loads(cleaned)
        fr_data = d.get("fr", {})
        en_data = d.get("en", {})
    except Exception as e:
        print(f"  ⚠️  JSON parse error: {e} — utilisation du fallback")

    def _clean_title(t: str, fallback: str) -> str:
        t = (t or "").strip().strip('"').strip("'").strip("«").strip("»").split("\n")[0][:100]
        return t if len(t) >= 20 else fallback

    def _clean_overlay(t: str, fallback: str) -> str:
        t = (t or "").strip().strip('"').strip("'").strip("«").strip("»").split("\n")[0]
        words = t.split()
        return t if 4 <= len(words) <= 12 else fallback

    def _clean_desc(t: str, fallback: str) -> str:
        t = (t or "").strip()
        return t[:500] if len(t) >= 60 else fallback

    fr_title_fb = f"{n} incontournables {niche_label} {month_fr} {year}"
    en_title_fb = f"{n} must-haves for {niche_label} {month_fr} {year}"
    fr_overlay_fb = f"{n} incontournables {niche_label} {month_fr}"
    en_overlay_fb = f"{n} essentials for {niche_label}"
    fr_desc_fb = f"Notre sélection {niche_label} de {month_fr} {year}. #{niche_label.replace(' ','').capitalize()} #{month_fr.capitalize()}{year}"
    en_desc_fb = f"Our {niche_label} selection for {month_fr} {year}. #{niche_label.replace(' ','').capitalize()} #{year}"

    pin_title_fr = _clean_title(fr_data.get("pin_title", ""), fr_title_fb)
    overlay_fr   = _clean_overlay(fr_data.get("overlay_hero", ""), fr_overlay_fb)
    description_fr = _clean_desc(fr_data.get("description", ""), fr_desc_fb)

    pin_title_en = _clean_title(en_data.get("pin_title", ""), en_title_fb)
    overlay_en   = _clean_overlay(en_data.get("overlay_hero", ""), en_overlay_fb)
    description_en = _clean_desc(en_data.get("description", ""), en_desc_fb)

    print(f"  ✅ PIN FR — overlay: {overlay_fr!r}  |  titre: {pin_title_fr}")
    print(f"  ✅ PIN EN — overlay: {overlay_en!r}  |  title: {pin_title_en}")

    return {
        "fr": {
            "pin_title": pin_title_fr,
            "overlay_hero": overlay_fr,
            "description": description_fr,
        },
        "en": {
            "pin_title": pin_title_en,
            "overlay_hero": overlay_en,
            "description": description_en,
        },
        "_prompts": {"combined": prompt},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GÉNÉRATION D'IMAGE (exactement le même prompt que le workflow)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_image(niche_label: str, image_style: str, variant: str,
                   save_to: Path, product_focus: str = "") -> str | None:
    if not HF_API_TOKEN:
        print("  ⚠️  HF_API_TOKEN manquant — image ignorée")
        return None
    if not _PIL:
        print("  ⚠️  Pillow non installé — image ignorée")
        return None

    # Prompt image enrichi + varié par produit focus
    focus_clause = f"featuring {product_focus} as hero product, " if product_focus else ""
    _base_prompt = (
        f"Photorealistic vertical Pinterest image 1000x1500, "
        f"premium aspirational lifestyle photography for {niche_label}. "
        f"{focus_clause}"
        f"Warm neutral palette (beige, ivory, sage green, taupe, warm white). "
        f"Soft natural daylight, large windows, high-end surfaces "
        f"(light oak, linen, ceramic, matte metal, brushed concrete). "
        f"Calm, curated, luxurious mood. 8K photorealistic, shallow depth of field, "
        f"bokeh background. No people, no faces. "
        f"ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, NO LOGOS, NO WATERMARKS anywhere."
    )
    variant_suffix = {
        "hero": ", wide establishing flat-lay shot, golden morning light, top-down view",
        "spotlight": ", warm afternoon sidelight, cinematic close-up, macro detail",
        "checklist": ", soft diffused morning light, minimal flat-lay, overhead angle",
    }
    full_prompt = f"{_base_prompt} {image_style}{variant_suffix.get(variant, '')}"

    NO_TEXT_HEADER = (
        "PURE PHOTOGRAPH with ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, "
        "NO NUMBERS, NO LABELS, NO SIGNS, NO LOGOS, NO WATERMARKS, "
        "NO CAPTIONS, NO WRITING OF ANY KIND anywhere in the image. "
        "All product surfaces must be plain and label-free. "
        "Professional interior photography only. Scene: "
    )

    print(f"\n{'─'*60}")
    print(f"  🎨 PROMPT IMAGE [{variant}] (envoyé à HF FLUX.1-schnell) :")
    print(f"{'─'*60}")
    print(NO_TEXT_HEADER + full_prompt)
    print(f"{'─'*60}\n")

    url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": NO_TEXT_HEADER + full_prompt,
               "parameters": {"width": PIN_W, "height": PIN_H}}

    print(f"  ⏳ Génération en cours…")
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code != 200:
            print(f"  ❌ HF {resp.status_code}: {resp.text[:150]}")
            return None
        from io import BytesIO
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        img = img.resize((PIN_W, PIN_H), Image.LANCZOS)
        save_to.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(save_to), "JPEG", quality=90)
        print(f"  ✅ Image brute → {save_to}")
        return str(save_to)
    except Exception as e:
        print(f"  ❌ Erreur HF: {e}")
        return None


def add_overlay(image_path: str, overlay_text: str) -> str | None:
    """Applique le text overlay Caveat (même logique que le workflow)."""
    if not _PIL:
        return None
    try:
        from create_and_post_top_products import _add_text_overlay
        img = Image.open(image_path)
        _add_text_overlay(img, overlay_text, image_path)
        print(f"  ✅ Overlay appliqué → {image_path}")
        return image_path
    except Exception as e:
        print(f"  ⚠️  Overlay échoué: {e}")
        return None


def save_article_txt(out_dir: Path, title_fr: str, title_en: str,
                     fr_body: str, en_body: str, products: list, n: int,
                     niche_label: str, month_fr: str, year: str,
                     prompt_body: str = "") -> None:
    """Sauvegarde article_fr.txt et article_en.txt."""
    sep = "═" * 60
    for lang, title, body in [("fr", title_fr, fr_body), ("en", title_en, en_body)]:
        lines = [
            sep,
            f"  ARTICLE {'FR' if lang == 'fr' else 'EN'} — INPUTS",
            sep,
            "",
            f"  Modèle article  : {OLLAMA_CLOUD_MODEL}",
            f"  Niche           : {niche_label}",
            f"  Mois            : {month_fr} {year}",
            f"  Nb produits     : {n}",
            f"  Titre source    : overlay de pin_01 ({'FR' if lang == 'fr' else 'EN'})",
            "",
        ]
        if lang == "fr" and prompt_body:
            lines += [
                f"  ── PROMPT CORPS ARTICLE {'─'*35}",
                *[f"  {l}" for l in prompt_body.splitlines()],
                "",
            ]
        lines += [
            sep,
            "",
            f"TITRE ARTICLE ({'FR' if lang == 'fr' else 'EN'})",
            "─" * 60,
            title,
            "",
            f"CORPS DE L'ARTICLE ({'français' if lang == 'fr' else 'english'})",
            "─" * 60,
            body if body else "(pas de corps en mode --pin-only)",
            "",
            f"PRODUITS SÉLECTIONNÉS ({n})",
            f"{'─'*60}",
        ]
        for i, p in enumerate(products, 1):
            pt    = p.get("llm_product_type") or ""
            price = p.get("price") or "?"
            brand = p.get("brand") or "?"
            name  = (p.get("name") or "?")[:80]
            url   = p.get("affiliate_url") or ""
            lines.append(f"{i}. [{pt}] {brand} — {name} — {price} €")
            if url:
                lines.append(f"   🔗 {url}")
        lines += ["", f"Niche : {niche_label}  |  {month_fr} {year}"]
        fname = f"article_{lang}.txt"
        (out_dir / fname).write_text("\n".join(lines), encoding="utf-8")
        print(f"  💾 {fname}  → {out_dir / fname}")


def save_article_html(out_dir: Path, title: str, body: str, products: list,
                      niche_label: str, month_fr: str, year: str,
                      lang: str = "fr") -> None:
    """Génère article_preview_{lang}.html — aperçu visuel de l'article."""

    lang_label = "FR" if lang == "fr" else "EN"
    html_lang  = "fr" if lang == "fr" else "en"

    # ── Convertir le body Markdown-like → HTML ─────────────────────────────
    def body_to_html(text: str) -> str:
        if not text:
            return "<p><em>(corps non généré — mode --pin-only)</em></p>"
        html_parts = []
        for para in re.split(r"\n{2,}", text.strip()):
            para = para.strip()
            if not para:
                continue
            # Balises images produit → placeholder visuel (remplacé par vraie image si dispo)
            m = re.match(r"^\{\{PRODUCT_IMAGE:([^}]+)\}\}$", para)
            if m:
                slug = m.group(1)
                # Chercher l'image produit correspondante
                matched_img = ""
                for p in products:
                    p_slug = _slugify(f"{p.get('brand', '')}-{(p.get('name', '') or '')[:35]}")
                    if p_slug == slug:
                        matched_img = p.get("image_url") or ""
                        break
                if matched_img:
                    html_parts.append(
                        f'<div class="product-image-block">'
                        f'<img src="{matched_img}" alt="{slug}" class="product-inline-img">'
                        f'</div>'
                    )
                else:
                    html_parts.append(
                        f'<div class="product-image-placeholder">'
                        f'<span class="pi-icon">🖼</span>'
                        f'<span class="pi-label">Image produit</span>'
                        f'<code class="pi-tag">{{{{PRODUCT_IMAGE:{slug}}}}}</code>'
                        f'</div>'
                    )
            else:
                # Liens Markdown [texte](url) → <a>
                line = re.sub(
                    r"\[([^\]]+)\]\((https?://[^\)]+)\)",
                    r'<a href="\2" target="_blank" rel="noopener sponsored" class="affil-link">\1</a>',
                    para,
                )
                line = line.replace("\n", "<br>")
                html_parts.append(f"<p>{line}</p>")
        return "\n".join(html_parts)

    body_html = body_to_html(body)

    # ── Cards produits ───────────────────────────────────────────────────────
    def product_cards(prods: list) -> str:
        cards = []
        for p in prods:
            name   = (p.get("name")  or "?").strip()
            brand  = (p.get("brand") or "?").strip()
            price  = p.get("price") or "?"
            url    = p.get("affiliate_url") or "#"
            ptype  = (p.get("llm_product_type") or "").replace("_", " ")
            img_url = p.get("image_url") or ""
            if img_url:
                img_html = f'<img src="{img_url}" alt="{name}" class="product-card-photo">'
            else:
                img_html = '<div class="product-card-img-fallback">🛍</div>'
            cards.append(f"""
        <div class="product-card">
          <div class="product-card-img-wrap">{img_html}</div>
          <div class="product-card-body">
            <span class="product-type">{ptype}</span>
            <h3 class="product-name">{name}</h3>
            <p class="product-brand">{brand}</p>
            <p class="product-price">{price} €</p>
            <a class="product-btn" href="{url}" target="_blank" rel="noopener sponsored">
              {'Voir le produit →' if lang == 'fr' else 'View product →'}
            </a>
          </div>
        </div>""")
        return "\n".join(cards)

    niche_slug  = re.sub(r"[^a-z0-9-]", "", niche_label.replace(" ", "-").lower())
    article_url = f"{SITE_URL}/{lang}/blog/{niche_slug}/"

    products_heading = "Les produits" if lang == "fr" else "The products"
    debug_label = "Aperçu DEBUG" if lang == "fr" else "Debug Preview"

    html = f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — MyGoodPick [{lang_label}]</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f5f4f0;
      color: #1a1a1a;
      line-height: 1.7;
    }}
    .site-header {{
      background: #0e1424;
      color: #fff;
      padding: 14px 0;
      text-align: center;
    }}
    .site-header a {{ color: #10b981; font-weight: 700; font-size: 1.25rem; text-decoration: none; }}
    .site-header .tagline {{ font-size: .8rem; color: #90a3b0; margin-top: 2px; }}
    .lang-badge {{
      display: inline-block;
      background: #10b981;
      color: #fff;
      font-size: .7rem;
      font-weight: 800;
      padding: 2px 8px;
      border-radius: 4px;
      margin-left: 8px;
      vertical-align: middle;
    }}
    .container {{ max-width: 780px; margin: 0 auto; padding: 0 20px; }}
    .article-wrap {{
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 2px 16px rgba(0,0,0,.08);
      margin: 32px auto;
      max-width: 780px;
      overflow: hidden;
    }}
    .article-hero {{
      background: linear-gradient(130deg, #0e1424 0%, #162038 60%, #10b981 140%);
      padding: 52px 40px 40px;
      color: #fff;
    }}
    .article-meta {{ font-size: .8rem; color: #10b981; letter-spacing: .06em;
                     text-transform: uppercase; margin-bottom: 12px; }}
    .article-title {{
      font-size: clamp(1.6rem, 4vw, 2.4rem);
      font-weight: 800;
      line-height: 1.2;
      margin-bottom: 16px;
    }}
    .article-url {{ font-size: .8rem; color: #90a3b0; }}
    .article-url a {{ color: #90a3b0; }}
    .article-body {{ padding: 36px 40px; }}
    .article-body p {{ margin-bottom: 1.2em; color: #333; }}
    .article-body a.affil-link {{
      color: #0e7a58;
      font-weight: 600;
      text-decoration: underline;
      text-decoration-color: #10b98155;
      text-underline-offset: 3px;
    }}
    .article-body a.affil-link:hover {{ color: #10b981; }}
    /* Product inline image (from {{PRODUCT_IMAGE:...}} tag) */
    .product-image-block {{
      margin: 20px 0;
      border-radius: 10px;
      overflow: hidden;
      max-height: 340px;
    }}
    .product-inline-img {{
      width: 100%;
      max-height: 340px;
      object-fit: contain;
      background: #f0f4f8;
      display: block;
    }}
    .product-image-placeholder {{
      display: flex;
      align-items: center;
      gap: 12px;
      background: #f0f4f8;
      border: 2px dashed #c2d4e0;
      border-radius: 8px;
      padding: 18px 20px;
      margin: 20px 0;
      color: #6888a0;
      font-size: .9rem;
    }}
    .pi-icon {{ font-size: 1.6rem; }}
    .pi-label {{ font-weight: 600; }}
    .pi-tag {{ font-size: .75rem; color: #9ab; margin-left: auto;
               background: #e2eaf0; padding: 3px 8px; border-radius: 4px; }}
    .section-title {{
      font-size: 1.1rem;
      font-weight: 700;
      color: #0e1424;
      border-left: 4px solid #10b981;
      padding-left: 12px;
      margin: 36px 0 20px;
    }}
    .products-grid {{ display: grid; gap: 16px; }}
    .product-card {{
      display: flex;
      gap: 16px;
      background: #f8faf9;
      border: 1px solid #e0ede8;
      border-radius: 10px;
      padding: 18px;
      align-items: flex-start;
    }}
    .product-card-img-wrap {{
      width: 80px; height: 80px; min-width: 80px;
      border-radius: 8px;
      overflow: hidden;
      background: #e0ede8;
      display: flex; align-items: center; justify-content: center;
    }}
    .product-card-photo {{
      width: 80px; height: 80px;
      object-fit: cover;
      display: block;
    }}
    .product-card-img-fallback {{
      font-size: 2rem;
    }}
    .product-card-body {{ flex: 1; }}
    .product-type {{ font-size: .7rem; color: #10b981; text-transform: uppercase;
                     font-weight: 700; letter-spacing: .06em; }}
    .product-name {{ font-size: .95rem; font-weight: 700; margin: 4px 0 2px; color: #0e1424; }}
    .product-brand {{ font-size: .8rem; color: #7a8a98; }}
    .product-price {{ font-size: 1.1rem; font-weight: 800; color: #0e1424; margin: 6px 0; }}
    .product-btn {{
      display: inline-block;
      background: #10b981;
      color: #fff;
      padding: 7px 16px;
      border-radius: 6px;
      font-size: .82rem;
      font-weight: 700;
      text-decoration: none;
    }}
    .product-btn:hover {{ background: #0e7a58; }}
    .debug-badge {{
      display: inline-flex; align-items: center; gap: 6px;
      background: #fef3c7; color: #92400e;
      border: 1px solid #fcd34d;
      border-radius: 20px;
      font-size: .75rem; font-weight: 700;
      padding: 4px 12px;
      margin: 0 40px 0;
    }}
    .site-footer {{
      text-align: center;
      color: #8899a6;
      font-size: .78rem;
      padding: 24px 0 40px;
    }}
  </style>
</head>
<body>

<header class="site-header">
  <a href="{SITE_URL}">MyGoodPick<span class="lang-badge">{lang_label}</span></a>
  <div class="tagline">{'Sélections produits testées &amp; validées' if lang == 'fr' else 'Tested &amp; curated product picks'}</div>
</header>

<div class="container">
  <span class="debug-badge">🧪 {debug_label} — {month_fr} {year} [{lang_label}]</span>
</div>

<article class="article-wrap">

  <!-- Hero -->
  <div class="article-hero">
    <div class="article-meta">{niche_label} &nbsp;·&nbsp; {month_fr} {year}</div>
    <h1 class="article-title">{title}</h1>
    <div class="article-url"><a href="{article_url}">{article_url}</a></div>
  </div>

  <!-- Corps -->
  <div class="article-body">
    {body_html}

    <div class="section-title" style="margin-top:40px;">{products_heading} ({len(products)})</div>
    <div class="products-grid">
      {product_cards(products)}
    </div>
  </div>

</article>

<footer class="site-footer">
  {'Aperçu généré' if lang == 'fr' else 'Preview generated'} {month_fr} {year} — <a href="{SITE_URL}">{SITE_URL}</a>
</footer>

</body>
</html>"""

    fname = f"article_preview_{lang}.html"
    out_path = out_dir / fname
    out_path.write_text(html, encoding="utf-8")
    print(f"  💾 {fname} → {out_path}")


def save_pin_txt(out_dir: Path, pin: dict, niche: str, title_fr: str, title_en: str,
                 hero_path: str | None, spotlight_path: str | None,
                 pin_idx: int = 1) -> None:
    """Sauvegarde pin_{idx:02d}_fr.txt et pin_{idx:02d}_en.txt dans le dossier niche."""
    slug = re.sub(r"[^a-z0-9-]", "", niche.replace("_", "-").lower())
    prompts = pin.get("_prompts", {})

    for lang in ("fr", "en"):
        article_url = f"{SITE_URL}/{lang}/blog/{slug}/"
        title = title_fr if lang == "fr" else title_en
        lang_data = pin.get(lang, {})
        pin_title  = lang_data.get("pin_title", "")
        overlay    = lang_data.get("overlay_hero", "")
        desc       = lang_data.get("description", "")

        sep = "═" * 60
        filename = f"pin_{pin_idx:02d}_{lang}.txt"
        lines = [
            sep,
            f"  INPUTS UTILISÉS POUR GÉNÉRER CE PIN ({filename})",
            sep,
            "",
            f"  Modèle pins  : {OLLAMA_CLOUD_PINS_MODEL}",
            f"  Niche        : {niche}",
            f"  Variation    : {pin_idx}",
            f"  Langue       : {lang.upper()}",
            f"  Titre article de référence : {title}",
            "",
        ]
        combined_prompt = prompts.get("combined", "")
        if combined_prompt:
            lines += [
                f"  ── PROMPT PIN BILINGUE {'─' * 40}",
                *[f"  {l}" for l in combined_prompt.splitlines()],
                "",
            ]
        lines += [
            sep,
            "",
            f"TITRE PIN ({lang.upper()})",
            "─" * 60,
            pin_title,
            "",
            f"DESCRIPTION + HASHTAGS ({lang.upper()})",
            f"{'─'*60}",
            desc,
            "",
            f"OVERLAY IMAGE ({lang.upper()})",
            f"{'─'*60}",
            overlay,
            "",
            f"URL ARTICLE ({lang.upper()})",
            f"{'─'*60}",
            article_url,
            "",
            f"TITRE ARTICLE DE RÉFÉRENCE ({lang.upper()})",
            f"{'─'*60}",
            title,
            "",
            f"IMAGES",
            f"{'─'*60}",
            f"hero      : {hero_path or '(non générée)'}",
            f"spotlight : {spotlight_path or '(non générée)'}",
        ]
        (out_dir / filename).write_text("\n".join(lines), encoding="utf-8")
        print(f"  💾 {filename}  → {out_dir / filename}")


# ═══════════════════════════════════════════════════════════════════════════════
# TRAITEMENT D'UNE NICHE
# ═══════════════════════════════════════════════════════════════════════════════

def process_niche(niche: str, taxonomy: dict, month_fr: str, year: str,
                  nb_products: int, gen_images: bool, pin_only: bool,
                  nb_pins: int = 1) -> None:
    niche_cfg   = taxonomy.get("niche_config", {}).get(niche, {})
    niche_label = niche_cfg.get("label_fr", niche.replace("_", " "))
    image_style = niche_cfg.get(
        "image_style",
        f"Modern interior design for {niche_label}, cozy lifestyle photography"
    )

    print(f"\n{'═'*70}")
    print(f"  🎯 NICHE : {niche.upper()}  ({niche_label})")
    print(f"     Mois          : {month_fr} {year}")
    print(f"     Produits      : {nb_products}")
    print(f"     Variations pin: {nb_pins}")
    print(f"     Images        : {'oui' if gen_images else 'non (--no-image)'}")
    print(f"     Mode          : {'pin-only (sans titre/intro)' if pin_only else 'complet'}")
    print(f"     LLM art       : {OLLAMA_CLOUD_MODEL}")
    print(f"     LLM pins      : {OLLAMA_CLOUD_PINS_MODEL}")
    print(f"{'═'*70}")

    # ── 1. Produits depuis Supabase ───────────────────────────────────────────
    print(f"\n  🔍 REQUÊTE SUPABASE")
    print(f"  {'─'*60}")
    url = (f"{SUPABASE_URL}/rest/v1/products?"
           f"llm_niches=cs.{{{niche}}}&active=not.is.false"
           f"&select=id,name,brand,image_url,price,currency,llm_product_type,affiliate_url"
           f"&order=rating.desc.nullslast,review_count.desc.nullslast&limit={nb_products * 10}")
    print(f"  GET {url[:100]}…")
    products = fetch_products_for_niche(niche, taxonomy, count=nb_products)
    if not products:
        print(f"  ❌ Aucun produit trouvé pour '{niche}' — niche ignorée")
        return
    n = len(products)
    print(f"\n  📦 {n} produits récupérés :")
    for i, p in enumerate(products, 1):
        pt    = p.get("llm_product_type") or "?"
        brand = p.get("brand") or "?"
        name  = (p.get("name") or "?")[:55]
        price = p.get("price") or "?"
        print(f"     {i}. [{pt}]  {brand} — {name} — {price} €")

    product_list = "\n".join(
        f"{i+1}. {p.get('name','?')} ({p.get('brand','?')}, {p.get('price','?')} €)"
        for i, p in enumerate(products)
    )

    # ── 2. Dossier de sortie par niche ────────────────────────────────────────
    out_dir = TEST_OUTPUT / niche
    out_dir.mkdir(parents=True, exist_ok=True)

    # Titre de référence provisoire pour les prompts pin
    ref_title = f"Sélection {niche_label} — {month_fr} {year}"

    # ── 3. Boucle variations de pin (on génère les pins en premier) ───────────
    import random as _rnd
    pins_data: list[tuple] = []   # (pin_dict, hero_path, spotlight_path)
    for pin_idx in range(1, nb_pins + 1):
        print(f"\n{'─'*70}")
        print(f"  📌 VARIATION PIN {pin_idx}/{nb_pins}")
        print(f"{'─'*70}")

        # Produits légèrement mélangés à partir de la variation 2
        if pin_idx > 1:
            products_var = products[:]
            _rnd.shuffle(products_var)
            product_list_var = "\n".join(
                f"{i+1}. {p.get('name','?')} ({p.get('brand','?')}, {p.get('price','?')} €)"
                for i, p in enumerate(products_var)
            )
            focus = products_var[0].get("llm_product_type", "").replace("_", " ")
        else:
            product_list_var = product_list
            focus = products[0].get("llm_product_type", "").replace("_", " ")

        pin = generate_pin_content(
            ref_title, n, niche_label, product_list_var, month_fr, year,
            variation_num=pin_idx, nb_variations=nb_pins
        )

        # Images pour cette variation
        hero_path: str | None = None
        spotlight_path: str | None = None
        if gen_images:
            hero_save = out_dir / f"hero_{pin_idx:02d}.jpg"
            spot_save = out_dir / f"spotlight_{pin_idx:02d}.jpg"

            hero_path = generate_image(niche_label, image_style, "hero", hero_save,
                                       product_focus=focus)
            if hero_path:
                add_overlay(hero_path, pin["fr"]["overlay_hero"])

            spotlight_path = generate_image(niche_label, image_style, "spotlight", spot_save,
                                            product_focus=focus)
            if spotlight_path:
                add_overlay(spotlight_path, f"Top {n} {niche_label}")

        pins_data.append((pin, hero_path, spotlight_path))

        if pin_idx < nb_pins:
            time.sleep(2)

    # ── 4. Titres article = overlay de pin_01 (FR et EN) ─────────────────────
    article_title_fr = pins_data[0][0]["fr"]["overlay_hero"]
    article_title_en = pins_data[0][0]["en"]["overlay_hero"]
    print(f"\n  📌 TITRE ARTICLE FR (depuis overlay pin_01) : {article_title_fr!r}")
    print(f"  📌 TITRE ARTICLE EN (depuis overlay pin_01) : {article_title_en!r}")

    # ── 5. Board Pinterest cible ──────────────────────────────────────────────
    board_name_fr, board_id_fr = get_board_for_niche(niche, "fr")
    board_name_en, board_id_en = get_board_for_niche(niche, "en")
    print(f"\n  🗂  Board FR : {board_name_fr or '(non configuré)'}  [{board_id_fr or 'ID à remplir'}]")
    print(f"  🗂  Board EN : {board_name_en or '(non configuré)'}  [{board_id_en or 'ID à remplir'}]")

    # ── 6. Corps de l'article (bilingue) ─────────────────────────────────────
    print(f"\n  💾 SAUVEGARDE DANS {out_dir}/")
    if not pin_only:
        fr_body, en_body, prompt_body = generate_article_body(
            article_title_fr, article_title_en, products, niche_label, month_fr, year
        )
        print(f"\n  ✅ CORPS ARTICLE — FR : {len(fr_body.split())} mots  |  EN : {len(en_body.split())} mots")
    else:
        fr_body = en_body = ""
        prompt_body = ""
        print(f"  ⚡ Mode pin-only — corps article ignoré")

    # ── 7. Sauvegarde article (FR + EN) ──────────────────────────────────────
    save_article_txt(out_dir, article_title_fr, article_title_en,
                     fr_body, en_body, products, n,
                     niche_label, month_fr, year, prompt_body=prompt_body)
    save_article_html(out_dir, article_title_fr, fr_body, products,
                      niche_label, month_fr, year, lang="fr")
    save_article_html(out_dir, article_title_en, en_body, products,
                      niche_label, month_fr, year, lang="en")

    # ── 8. Sauvegarde des pins (FR + EN, avec titres article finaux) ──────────
    for pin_idx, (pin, hero_path, spotlight_path) in enumerate(pins_data, 1):
        save_pin_txt(out_dir, pin, niche, article_title_fr, article_title_en,
                     hero_path, spotlight_path, pin_idx=pin_idx)

    print(f"\n  ✅ Niche {niche} terminée")
    print(f"     📁 {out_dir}/")
    files_out = [f.name for f in sorted(out_dir.glob("*")) if f.is_file()]
    for f in files_out:
        print(f"        {f}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Test génération pins sur 3 niches — affiche tous les prompts LLM "
                    "et sauvegarde les résultats par niche dans tests/output/")
    parser.add_argument("--no-image", action="store_true",
                        help="Désactiver la génération d'images (texte seul)")
    parser.add_argument("--pin-only", action="store_true",
                        help="Sauter titre article + intro — aller direct pin content + images")
    parser.add_argument("--niches", nargs="+", default=None,
                        metavar="NICHE",
                        help=f"Niches à tester (défaut: {' '.join(DEFAULT_TEST_NICHES)})")
    parser.add_argument("--month", default=None,
                        help="Mois cible YYYY-MM (défaut: mois courant)")
    parser.add_argument("--nb-products", type=int, default=5,
                        help="Nombre de produits par niche (défaut: 5)")
    parser.add_argument("--nb-pins", type=int, default=2,
                        help="Nombre de variations de pin par niche (défaut: 2)")
    args = parser.parse_args()

    month    = args.month or datetime.now().strftime("%Y-%m")
    year, mo = month.split("-")
    month_fr = MONTH_FR.get(mo, mo)
    niches   = args.niches or DEFAULT_TEST_NICHES

    # Charger la taxonomie
    if not TAXONOMY_PATH.exists():
        print(f"❌ {TAXONOMY_PATH} introuvable")
        sys.exit(1)
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))

    print(f"\n{'═'*70}")
    print(f"  🧪  TEST PIN CREATION — {len(niches)} NICHE(S)")
    print(f"  Niches   : {', '.join(niches)}")
    print(f"  Mois     : {month_fr} {year}")
    print(f"  Produits : {args.nb_products} par niche")
    print(f"  Pins/var : {args.nb_pins} variation(s) par niche")
    print(f"  Images   : {'non' if args.no_image else 'oui (hero + spotlight par variation)'}")
    print(f"  Mode     : {'pin-only' if args.pin_only else 'complet'}")
    print(f"  Output   : {TEST_OUTPUT}/")
    print(f"{'═'*70}")

    for i, niche in enumerate(niches):
        process_niche(
            niche       = niche,
            taxonomy    = taxonomy,
            month_fr    = month_fr,
            year        = year,
            nb_products = args.nb_products,
            gen_images  = not args.no_image,
            pin_only    = args.pin_only,
            nb_pins     = args.nb_pins,
        )
        if i < len(niches) - 1:
            print(f"\n  ⏳ Pause 3s avant la prochaine niche…")
            time.sleep(3)

    # ── Résumé final ──────────────────────────────────────────────────────────
    print(f"\n{'═'*70}")
    print(f"  ✅ TEST TERMINÉ — {len(niches)} niche(s) traitée(s)")
    print(f"  📁 Fichiers générés dans {TEST_OUTPUT}/")
    for niche in niches:
        nd = TEST_OUTPUT / niche
        files = [f.name for f in sorted(nd.glob("*")) if f.is_file()] if nd.exists() else []
        print(f"     {niche}/  →  {', '.join(files) if files else '(vide)'}")
    print(f"{'═'*70}\n")


if __name__ == "__main__":
    main()
