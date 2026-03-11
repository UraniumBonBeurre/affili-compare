#!/usr/bin/env python3
"""
generate-content.py — Génère du contenu SEO pour les comparatifs via LLM

Pipeline :
  1. Lit les comparatifs Supabase sans contenu (ou --force-all)
  2. Pour chaque comparatif, génère via LLM :
       - intro (300 mots, texte riche)
       - buying_guide (500 mots, guide d'achat)
       - faq (5 Q&A JSON)
  3. Sauvegarde dans Supabase : comparisons.intro, buying_guide, faq_json
  4. Déclenche la revalidation ISR Vercel via /api/revalidate

Modèles LLM supportés :
  - Ollama local (si disponible) → mistral:7b ou llama3.2:3b
  - Hugging Face Inference API (fallback)

Usage :
    python scripts/generate-content.py                          # Comparatifs sans contenu
    python scripts/generate-content.py --comparison-id 3       # Un seul
    python scripts/generate-content.py --force-all             # Régénère tout
    python scripts/generate-content.py --dry-run               # Affiche le prompt sans appel LLM

Environment variables:
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
    SITE_URL, REVALIDATE_SECRET                    # ISR revalidation
    HF_API_TOKEN                                    # Si Ollama non dispo
    OLLAMA_HOST (optionnel, défaut: http://localhost:11434)
"""

import argparse
import json
import os
import re
import sys
import textwrap
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SITE_URL = os.getenv("SITE_URL", "https://affili-compare.com").rstrip("/")
REVALIDATE_SECRET = os.getenv("REVALIDATE_SECRET", "")
HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# LLM preferences
OLLAMA_MODELS = ["mistral:7b", "llama3.2:3b", "llama3:8b"]
HF_TEXT_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _sb_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def fetch_comparisons_without_content(limit: int = 20) -> list[dict]:
    """Fetch comparisons where intro IS NULL."""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/comparisons"
        "?status=eq.published"
        "&intro=is.null"
        "&select=id,title,slug,meta_description,category_id,categories(name,slug)"
        f"&limit={limit}",
        headers=_sb_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_comparison_products(comparison_id: int) -> list[dict]:
    """Fetch products for a comparison with affiliate link prices."""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/comparison_products"
        f"?comparison_id=eq.{comparison_id}"
        "&select=position,products(name,brand,rating,review_count,pros,cons,affiliate_links(partner_id,price,in_stock))"
        "&order=position.asc",
        headers=_sb_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def update_comparison_content(comparison_id: int, content: dict) -> None:
    """Update intro, buying_guide, faq_json in Supabase."""
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/comparisons?id=eq.{comparison_id}",
        headers=_sb_headers(),
        json={
            "intro": content.get("intro"),
            "buying_guide": content.get("buying_guide"),
            "faq_json": content.get("faq"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        timeout=10,
    )
    resp.raise_for_status()


# ── LLM backends ─────────────────────────────────────────────────────────────

def _ollama_available() -> Optional[str]:
    """Return the first available Ollama model, or None."""
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        if resp.status_code == 200:
            available = {m["name"] for m in resp.json().get("models", [])}
            for model in OLLAMA_MODELS:
                if model in available:
                    return model
    except Exception:
        pass
    return None


def _call_ollama(model: str, prompt: str) -> str:
    """Call local Ollama API."""
    resp = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def _call_hf(prompt: str) -> str:
    """Call Hugging Face Inference API."""
    if not HF_API_TOKEN:
        raise RuntimeError("HF_API_TOKEN absent et Ollama non disponible.")
    url = f"https://api-inference.huggingface.co/models/{HF_TEXT_MODEL}"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {HF_API_TOKEN}"},
        json={
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 1024,
                "temperature": 0.7,
                "return_full_text": False,
            },
        },
        timeout=120,
    )
    if resp.status_code == 503:
        time.sleep(30)
        return _call_hf(prompt)
    resp.raise_for_status()
    result = resp.json()
    if isinstance(result, list):
        return result[0].get("generated_text", "")
    return str(result)


def call_llm(prompt: str, model: Optional[str] = None) -> str:
    """Call LLM with Ollama preference, HF fallback."""
    ollama_model = model or _ollama_available()
    if ollama_model:
        print(f"  🤖 Ollama ({ollama_model}) …")
        return _call_ollama(ollama_model, prompt)
    else:
        print(f"  🤖 HF ({HF_TEXT_MODEL}) …")
        return _call_hf(prompt)


# ── Prompt builders ───────────────────────────────────────────────────────────

def _product_summary(products: list[dict]) -> str:
    lines = []
    for i, cp in enumerate(products, 1):
        p = cp.get("products", {})
        if not p:
            continue
        links = p.get("affiliate_links", [])
        prices = [l["price"] for l in links if l.get("price")]
        price_str = f"{min(prices):.0f}€" if prices else "prix NC"
        pros = ", ".join((p.get("pros") or [])[:2])
        lines.append(f"  {i}. {p.get('name', '')} ({price_str}) — {pros}")
    return "\n".join(lines)


def build_intro_prompt(comparison: dict, products: list[dict]) -> str:
    title = comparison.get("title", "")
    category = comparison.get("categories", {}).get("name", "") if comparison.get("categories") else ""
    prod_summary = _product_summary(products)
    year = datetime.now().year

    return textwrap.dedent(f"""
        Tu es un rédacteur expert en électroménager et équipement maison pour un comparateur produits français.
        Écris une introduction engageante de 280 à 320 mots en français pour l'article comparatif suivant.

        Titre : {title}
        Catégorie : {category}
        Année : {year}

        Produits comparés :
        {prod_summary}

        Instructions :
        - Commence par une accroche sur le besoin du lecteur (pas "Vous cherchez le meilleur...")
        - Mentionne les critères clés du comparatif
        - Cite les 2-3 produits les plus importants naturellement dans le texte
        - Ton journalistique, neutre, factuel
        - Pas de liste à puces, uniquement prose
        - Ne jamais promettre le "meilleur" sans nuance
        - Langue : français, niveau B2/C1
        - PAS de titre ni de sous-titre, uniquement le texte pur

        Texte :
    """).strip()


def build_buying_guide_prompt(comparison: dict, products: list[dict]) -> str:
    title = comparison.get("title", "")
    category = comparison.get("categories", {}).get("name", "") if comparison.get("categories") else ""
    prod_summary = _product_summary(products)

    return textwrap.dedent(f"""
        Tu es un expert conseil pour l'achat de {category} en France.
        Écris un guide d'achat de 480 à 520 mots en français pour aider le lecteur à choisir.
        Thème : {title}

        Produits du comparatif :
        {prod_summary}

        Structure requise (sans numérotation visible, enchaîner naturellement) :
        1. Les critères essentiels (puissance/autonomie/efficacité selon la catégorie)
        2. Ce qu'il faut éviter (erreurs courantes)
        3. Quel budget prévoir (entrée/milieu/haut de gamme)
        4. Notre conseil final en 2 phrases

        Règles :
        - Concret et actionnable, pas de remplissage
        - Chiffres précis quand possible
        - Mentions naturelles des produits du comparatif
        - Pas de jargon technique non expliqué
        - PAS de sous-titres HTML, prose directe

        Guide :
    """).strip()


def build_faq_prompt(comparison: dict, products: list[dict]) -> str:
    title = comparison.get("title", "")
    category = comparison.get("categories", {}).get("name", "") if comparison.get("categories") else ""

    return textwrap.dedent(f"""
        Génère exactement 5 questions-réponses FAQ en français pour le comparatif : {title}
        Catégorie : {category}

        Format JSON strict, UNIQUEMENT le JSON, pas d'explication :
        [
          {{"question": "...", "answer": "..."}},
          {{"question": "...", "answer": "..."}},
          {{"question": "...", "answer": "..."}},
          {{"question": "...", "answer": "..."}},
          {{"question": "...", "answer": "..."}}
        ]

        Règles :
        - Questions réelles que poserait un acheteur (50% questions prix/budget)
        - Réponses utiles de 2-3 phrases maximum
        - Données de {datetime.now().year}
        - Ne pas inventer de prix fictifs, utiliser des fourchettes
    """).strip()


def _extract_json_faq(text: str) -> list[dict]:
    """Extract JSON array from LLM output (may have surrounding text)."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return [{"question": "—", "answer": "—"}]


# ── ISR revalidation ─────────────────────────────────────────────────────────

def trigger_revalidation(slug: str, category_slug: str, locale: str = "fr") -> None:
    """Trigger Vercel ISR revalidation for a comparison page."""
    if not SITE_URL or not REVALIDATE_SECRET:
        return
    path = f"/{locale}/{category_slug}/{slug}"
    try:
        resp = requests.post(
            f"{SITE_URL}/api/revalidate",
            json={"secret": REVALIDATE_SECRET, "path": path},
            timeout=10,
        )
        if resp.status_code in (200, 204):
            print(f"  ✅ ISR revalidé : {path}")
        else:
            print(f"  ⚠  ISR {resp.status_code} pour {path}")
    except Exception as e:
        print(f"  ⚠  ISR erreur : {e}")


# ── Core ──────────────────────────────────────────────────────────────────────

def generate_content_for(comparison: dict, dry_run: bool = False) -> bool:
    """Generate and save content for one comparison. Returns True on success."""
    comp_id = comparison["id"]
    title = comparison.get("title", f"#{comp_id}")
    print(f"\n\033[1;34m  📝 {title} (id={comp_id})\033[0m")

    # Fetch products
    products = fetch_comparison_products(comp_id)
    if not products:
        print("  ⚠  Aucun produit trouvé. Skip.")
        return False

    # Build prompts
    intro_prompt = build_intro_prompt(comparison, products)
    guide_prompt = build_buying_guide_prompt(comparison, products)
    faq_prompt = build_faq_prompt(comparison, products)

    if dry_run:
        print("\n  [DRY RUN] Prompt intro :")
        print(textwrap.indent(intro_prompt[:400], "    > "))
        return True

    # Generate content
    print("  Intro …")
    intro = call_llm(intro_prompt).strip()

    time.sleep(2)  # Small delay between LLM calls

    print("  Buying guide …")
    buying_guide = call_llm(guide_prompt).strip()

    time.sleep(2)

    print("  FAQ …")
    faq_raw = call_llm(faq_prompt).strip()
    faq = _extract_json_faq(faq_raw)

    # Validate minimum lengths
    if len(intro) < 100:
        print(f"  ⚠  Intro trop courte ({len(intro)} chars). Skip.")
        return False
    if len(buying_guide) < 100:
        print(f"  ⚠  Guide trop court ({len(buying_guide)} chars). Skip.")
        return False

    # Save to Supabase
    update_comparison_content(comp_id, {
        "intro": intro,
        "buying_guide": buying_guide,
        "faq": faq,
    })
    print(f"  ✅ Contenu sauvé ({len(intro)} + {len(buying_guide)} chars, {len(faq)} FAQ)")

    # Trigger ISR
    slug = comparison.get("slug", "")
    category_slug = comparison.get("categories", {}).get("slug", "") if comparison.get("categories") else ""
    if slug and category_slug:
        trigger_revalidation(slug, category_slug)

    return True


def main():
    parser = argparse.ArgumentParser(description="Génère du contenu LLM pour AffiliCompare")
    parser.add_argument("--comparison-id", type=int, help="ID spécifique")
    parser.add_argument("--force-all", action="store_true", help="Régénère même si contenu existant")
    parser.add_argument("--dry-run", action="store_true", help="Simule (affiche prompts)")
    parser.add_argument("--limit", type=int, default=10, help="Max comparatifs à traiter")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("\033[1;31m✗ SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis.\033[0m")
        sys.exit(1)

    print(f"\n\033[1;35m📝 AffiliCompare — Generate Content\033[0m")
    print(f"   Mode : {'DRY RUN' if args.dry_run else 'LIVE'}")

    if args.comparison_id:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/comparisons"
            f"?id=eq.{args.comparison_id}"
            "&select=id,title,slug,meta_description,categories(name,slug)",
            headers=_sb_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        comparisons = resp.json()
    elif args.force_all:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/comparisons"
            "?status=eq.published"
            "&select=id,title,slug,meta_description,categories(name,slug)"
            f"&limit={args.limit}",
            headers=_sb_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        comparisons = resp.json()
    else:
        comparisons = fetch_comparisons_without_content(limit=args.limit)

    if not comparisons:
        print("\n  Aucun comparatif à traiter.")
        sys.exit(0)

    print(f"\n   → {len(comparisons)} comparatif(s) :")
    for c in comparisons:
        print(f"      #{c['id']} {c['title']}")

    success = 0
    for comp in comparisons:
        ok = generate_content_for(comp, dry_run=args.dry_run)
        if ok:
            success += 1
        time.sleep(3)

    print(f"\n\033[1;32m✅ {success}/{len(comparisons)} comparatifs traités\033[0m\n")


if __name__ == "__main__":
    main()
