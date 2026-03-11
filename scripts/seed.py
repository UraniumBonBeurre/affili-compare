#!/usr/bin/env python3
"""
seed.py — Peuple Supabase avec 2 catégories de test + 6 produits réalistes.

Catégories :
  1. Aspirateurs sans fil (3 produits)
  2. Lampes de salon     (3 produits)

Liens affiliés : construits manuellement via Amazon Associates FR.
Format : https://www.amazon.fr/dp/[ASIN]?tag=[ASSOCIATE_TAG]

⚠️  Vérifier les ASINs sur amazon.fr avant de déployer en production.

Usage :
  SUPABASE_URL=https://xxx.supabase.co \
  SUPABASE_SERVICE_ROLE_KEY=eyJ... \
  AMAZON_ASSOCIATE_TAG_FR=monsite-21 \
  python scripts/seed.py
"""

import json
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env.local"))
except ImportError:
    pass

try:
    from supabase import create_client
except ImportError:
    print("pip install supabase python-dotenv")
    sys.exit(1)

SUPABASE_URL = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
AMAZON_TAG   = os.environ.get("AMAZON_ASSOCIATE_TAG_FR", "monsite-21")  # ← ton associate tag

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌  Variables manquantes : SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)


# ─────────────────────────────────────────────────────────────
# Données de seed
# ─────────────────────────────────────────────────────────────

CATEGORIES = [
    {
        "slug": "aspirateurs-sans-fil",
        "name_fr": "Aspirateurs sans fil",
        "name_en": "Cordless Vacuums",
        "name_de": "Kabellose Staubsauger",
        "meta_description_fr": "Comparatif des meilleurs aspirateurs sans fil : puissance, autonomie, prix. Notre sélection 2026.",
        "icon": "🌀",
        "display_order": 1,
        "is_active": True,
    },
    {
        "slug": "lampes-de-salon",
        "name_fr": "Lampes de salon",
        "name_en": "Living Room Lamps",
        "name_de": "Wohnzimmerlampen",
        "meta_description_fr": "Les meilleures lampes de salon comparées : design, intensité, connectivité smart. Guide 2026.",
        "icon": "💡",
        "display_order": 2,
        "is_active": True,
    },
]

# Format des produits :
# asin       → ASIN Amazon FR (⚠️ à vérifier sur amazon.fr)
# other_links → liens Fnac/Darty/Boulanger construits manuellement (placeholder — compléter avec vrais liens Awin)
PRODUCTS_BY_CATEGORY = {
    "aspirateurs-sans-fil": {
        "comparison": {
            "slug":      "meilleurs-aspirateurs-sans-fil-2026",
            "title_fr":  "Top 5 meilleurs aspirateurs sans fil 2026 – Comparatif & Avis",
            "title_en":  "Top 5 Best Cordless Vacuums 2026 – Full Comparison",
            "intro_fr": (
                "Trouver le meilleur aspirateur sans fil en 2026 peut sembler complexe face à l'offre "
                "pléthorique. Notre équipe a sélectionné les modèles les plus performants, testés sur "
                "parquet, moquette et poils d'animaux, pour vous aider à faire le bon choix."
            ),
            "buying_guide_fr": (
                "## Comment choisir son aspirateur sans fil\n\n"
                "**Puissance d'aspiration (Pa)** : visez 20 000 Pa minimum pour un usage quotidien. "
                "Les modèles haut de gamme atteignent 28 000 Pa.\n\n"
                "**Autonomie** : 40 minutes suffisent pour un appartement de 80 m². Préférez les "
                "modèles avec batterie amovible pour doubler la durée.\n\n"
                "**Poids** : au-dessous de 1,8 kg, le ménage devient un plaisir. Au-delà, les bras "
                "se fatiguent rapidement sur les sessions longues.\n\n"
                "**Filtration HEPA** : indispensable si vous avez des allergies ou des animaux."
            ),
            "faq_fr": [
                {
                    "question": "Quelle puissance pour un aspirateur sans fil ?",
                    "answer": "20 000 Pa pour un appartement standard, 25 000 Pa si vous avez des animaux. Le mode turbo est à réserver aux taches tenaces — il épuise la batterie en 10 minutes.",
                },
                {
                    "question": "Combien de temps dure la batterie d'un aspirateur sans fil ?",
                    "answer": "Entre 40 et 90 minutes selon le modèle et le mode d'utilisation. Le mode éco préserve l'autonomie, le mode max aspire comme un aspirateur filaire.",
                },
                {
                    "question": "Un aspirateur sans fil peut-il remplacer un aspirateur filaire ?",
                    "answer": "Oui, pour 80% des utilisateurs. Les modèles à partir de 400 € rivalisent avec les meilleurs filaires. Seul bémol : les grandes maisons (> 150 m²) nécessitent plusieurs charges.",
                },
            ],
            "is_published": True,
            "seo_score": 85,
        },
        "products": [
            {
                "name":         "Dyson V15 Detect",
                "brand":        "Dyson",
                # ⚠️ VÉRIFIER ASIN sur https://www.amazon.fr/s?k=Dyson+V15+Detect
                "asin":         "B09C5GTRFS",
                "rating":       4.7,
                "review_count": 4231,
                "badge":        "premium",
                "pros_fr":      ["Laser qui révèle la poussière invisible", "Puissance 240 AW record", "Affichage LCD temps réel", "Filtration HEPA certifiée"],
                "cons_fr":      ["Prix élevé (750 €+)", "Lourd (3,1 kg)", "Bac à poussière petit (0,76 L)"],
                "price":        749.00,
                "other_links": [
                    {"partner": "fnac",   "url_suffix": "/SearchResult/ResultList.aspx?Search=Dyson+V15+Detect", "price": 729.00},
                    {"partner": "darty",  "url_suffix": "/nav/recherche?text=Dyson+V15+Detect",             "price": 699.00},
                ],
            },
            {
                "name":         "Shark Stratos IZ400UKT",
                "brand":        "Shark",
                # ⚠️ VÉRIFIER ASIN sur https://www.amazon.fr/s?k=Shark+Stratos+IZ400
                "asin":         "B09TGG5CRK",
                "rating":       4.5,
                "review_count": 1876,
                "badge":        "best-value",
                "pros_fr":      ["Excellent rapport qualité/prix", "Anti-enchevêtrement cheveux", "2-en-1 avec aspirateur main", "Autonomie 60 min"],
                "cons_fr":      ["Design moins premium que Dyson", "Station de charge volumineuse"],
                "price":        399.00,
                "other_links": [
                    {"partner": "fnac",   "url_suffix": "/SearchResult/ResultList.aspx?Search=Shark+Stratos", "price": 389.00},
                ],
            },
            {
                "name":         "Philips SpeedPro Max Aqua XC7957",
                "brand":        "Philips",
                # ⚠️ VÉRIFIER ASIN sur https://www.amazon.fr/s?k=Philips+SpeedPro+Max+Aqua
                "asin":         "B08Y5LHKLZ",
                "rating":       4.3,
                "review_count": 952,
                "badge":        "budget",
                "pros_fr":      ["Aspiration + lavage simultanés", "Prix abordable", "Filtration allergie", "Léger (2,9 kg)"],
                "cons_fr":      ["Réservoir eau minuscule (150 mL)", "Puissance inférieure à Dyson"],
                "price":        279.99,
                "other_links": [
                    {"partner": "boulanger", "url_suffix": "/recherche/r/?text=Philips+SpeedPro+Max",  "price": 269.00},
                    {"partner": "darty",     "url_suffix": "/nav/recherche?text=Philips+SpeedPro+Max", "price": 289.00},
                ],
            },
        ],
    },

    "lampes-de-salon": {
        "comparison": {
            "slug":      "meilleures-lampes-salon-2026",
            "title_fr":  "Top 5 meilleures lampes de salon 2026 – Comparatif Design & Connecté",
            "title_en":  "Top 5 Best Living Room Lamps 2026 – Design & Smart Comparison",
            "intro_fr": (
                "Une belle lampe de salon transforme une pièce. En 2026, les options vont de la lampe "
                "design épurée à l'ampoule connectée pilotable depuis votre smartphone. Notre comparatif "
                "couvre les meilleurs modèles à tous les prix, du basique au premium connecté."
            ),
            "buying_guide_fr": (
                "## Choisir sa lampe de salon\n\n"
                "**Température de couleur** : 2 700 K (blanc chaud) pour une ambiance cosy, "
                "4 000 K (blanc neutre) pour lire. Les ampoules connectées permettent de régler "
                "ce paramètre à la demande.\n\n"
                "**Flux lumineux (lm)** : comptez 800 lm minimum pour éclairer une pièce de 15 m². "
                "Une ampoule 10 W LED classique équivaut à 75 W incandescent (800 lm).\n\n"
                "**Lampe connectée ou classique ?** : les modèles smart coûtent 2–5× plus cher "
                "mais permettent la programmation, les scènes lumineuses et l'intégration Alexa/GoogleHome."
            ),
            "faq_fr": [
                {
                    "question": "Quelle ampoule pour une lampe de salon ?",
                    "answer": "Choisissez une ampoule LED E27 de 9–12 W (800–1100 lm) en blanc chaud (2700 K) pour une ambiance cosy. En LED E14 pour les petites douilles.",
                },
                {
                    "question": "Est-ce que les lampes Philips Hue valent leur prix ?",
                    "answer": "Oui si vous utilisez déjà un écosystème domotique (Alexa, Google, Apple HomeKit). Seules, elles sont chères. En bundle starter, le rapport qualité/prix s'améliore.",
                },
                {
                    "question": "Peut-on mettre n'importe quelle ampoule connectée dans une lampe classique ?",
                    "answer": "Oui, tant que la douille correspond (E27 ou E14) et que la lampe n'a pas de variateur incompatible. Les ampoules Wi-Fi s'installent sans câblage supplémentaire.",
                },
            ],
            "is_published": True,
            "seo_score": 78,
        },
        "products": [
            {
                "name":         "Philips Hue White & Color Ambiance E27",
                "brand":        "Philips Hue",
                # ⚠️ VÉRIFIER ASIN sur https://www.amazon.fr/s?k=Philips+Hue+White+Color+E27
                "asin":         "B07QKJ7VPL",
                "rating":       4.6,
                "review_count": 8942,
                "badge":        "premium",
                "pros_fr":      ["16 millions de couleurs", "Compatible Alexa / Google / HomeKit", "Application intuitive", "Scènes dynamiques"],
                "cons_fr":      ["Nécessite le Bridge Hue (vendu séparément)", "Prix élevé à l'ampoule (50 €+)"],
                "price":        54.99,
                "other_links": [
                    {"partner": "fnac",      "url_suffix": "/SearchResult/ResultList.aspx?Search=Philips+Hue+E27", "price": 49.99},
                    {"partner": "boulanger", "url_suffix": "/recherche/r/?text=Philips+Hue+E27",                  "price": 52.00},
                ],
            },
            {
                "name":         "WiZ Smart LED E27 Filament Ambrée",
                "brand":        "WiZ",
                # ⚠️ VÉRIFIER ASIN sur https://www.amazon.fr/s?k=WiZ+smart+filament+E27
                "asin":         "B087YLB78S",
                "rating":       4.4,
                "review_count": 3214,
                "badge":        "best-value",
                "pros_fr":      ["Sans Bridge requis (Wi-Fi direct)", "Design filament authentique", "Compatible Alexa & Google", "Prix abordable"],
                "cons_fr":      ["Application WiZ moins complète que Hue", "Rendu ambre un peu trop orangé"],
                "price":        19.99,
                "other_links": [
                    {"partner": "boulanger", "url_suffix": "/recherche/r/?text=WiZ+filament", "price": 18.99},
                ],
            },
            {
                "name":         "EGLO LED Ampoule Vintage Edison E27",
                "brand":        "EGLO",
                # ⚠️ VÉRIFIER ASIN sur https://www.amazon.fr/s?k=EGLO+LED+Edison+E27+vintage
                "asin":         "B07KDMZLHZ",
                "rating":       4.2,
                "review_count": 1567,
                "badge":        "budget",
                "pros_fr":      ["Design vintage authentique", "Très petit prix", "Bonne longévité (15 000h)", "Dimmable"],
                "cons_fr":      ["Non connectée", "Flux lumineux limité (400 lm)"],
                "price":        9.99,
                "other_links": [
                    {"partner": "maison-du-monde", "url_suffix": "/fr/fr/search/?q=ampoule+vintage", "price": 11.90},
                    {"partner": "la-redoute",      "url_suffix": "/ppp/search/result.htm?expression=ampoule+vintage", "price": 12.99},
                ],
            },
        ],
    },
}

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def build_amazon_url(asin: str) -> str:
    """Construit un lien affilié Amazon FR avec l'associate tag."""
    return f"https://www.amazon.fr/dp/{asin}?tag={AMAZON_TAG}"


PARTNER_DOMAINS = {
    "fnac":           "https://www.fnac.com",
    "darty":          "https://www.darty.com",
    "boulanger":      "https://www.boulanger.com",
    "maison-du-monde": "https://www.maisonsdumonde.com",
    "la-redoute":     "https://www.laredoute.fr",
}

PARTNER_COUNTRIES = {
    "fnac":           "fr",
    "darty":          "fr",
    "boulanger":      "fr",
    "maison-du-monde": "fr",
    "la-redoute":     "fr",
}


def build_partner_url(partner: str, url_suffix: str) -> str:
    """Construit un lien partenaire (placeholder Awin — à enrichir avec vrais paramètres Awin)."""
    base = PARTNER_DOMAINS.get(partner, f"https://{partner}.com")
    return base + url_suffix


def upsert(table: str, data: dict, conflict_col: str) -> dict:
    res = sb.table(table).upsert(data, on_conflict=conflict_col).execute()
    if not res.data:
        raise RuntimeError(f"Upsert failed on {table}: {data}")
    return res.data[0]


# ─────────────────────────────────────────────────────────────
# Seed principal
# ─────────────────────────────────────────────────────────────

def seed() -> None:
    print("🌱  Seed AffiliCompare — 2 catégories, 6 produits, liens Amazon manuels\n")

    for cat_data in CATEGORIES:
        # 1. Upsert catégorie
        category = upsert("categories", cat_data, "slug")
        cat_id   = category["id"]
        print(f"📂  Catégorie : {cat_data['name_fr']} (id={cat_id})")

        entry = PRODUCTS_BY_CATEGORY[cat_data["slug"]]

        # 2. Upsert comparaison
        comp_payload = {
            **entry["comparison"],
            "category_id": cat_id,
        }
        for field in ("faq_fr", "faq_en", "faq_de"):
            if isinstance(comp_payload.get(field), list):
                comp_payload[field] = json.dumps(comp_payload[field], ensure_ascii=False)

        comparison = upsert("comparisons", comp_payload, "slug")
        comp_id    = comparison["id"]
        print(f"   📄  Comparaison : {entry['comparison']['slug']}")

        # 3. Produits + liens affiliés
        for position, prod in enumerate(entry["products"], start=1):
            asin        = prod.pop("asin")
            other_links = prod.pop("other_links", [])
            price       = prod.pop("price", None)

            for field in ("pros_fr", "cons_fr"):
                if isinstance(prod.get(field), list):
                    prod[field] = json.dumps(prod[field], ensure_ascii=False)

            product = upsert("products", prod, "name")
            prod_id  = product["id"]
            print(f"   🛒  Produit [{position}] : {prod['name']} — ASIN {asin}")

            # Jointure comparison_products
            upsert("comparison_products", {
                "comparison_id": comp_id,
                "product_id":    prod_id,
                "position":      position,
            }, "comparison_id,product_id")

            # Lien Amazon (manuel, associate tag)
            _upsert_link(prod_id, comp_id, "amazon_fr", "fr", build_amazon_url(asin), price, "EUR")
            print(f"      🔗  Amazon FR → {build_amazon_url(asin)}")

            # Liens autres marchands (placeholder — sera enrichi par Awin)
            for link in other_links:
                url = build_partner_url(link["partner"], link["url_suffix"])
                _upsert_link(prod_id, comp_id, link["partner"], PARTNER_COUNTRIES.get(link["partner"], "fr"),
                             url, link.get("price"), "EUR")
                print(f"      🔗  {link['partner']:<16} → {link['price']} €  (placeholder Awin)")

        print()

    # Résumé
    print("✅  Seed terminé !\n")
    for table in ["categories", "comparisons", "products", "comparison_products", "affiliate_links"]:
        count = sb.table(table).select("id", count="exact").execute()
        print(f"   {table:<28} {count.count} ligne(s)")


def _upsert_link(product_id, comparison_id, partner, country, url, price, currency):
    existing = (sb.table("affiliate_links")
                .select("id")
                .eq("product_id", product_id)
                .eq("partner", partner)
                .execute())
    payload = {
        "product_id":    product_id,
        "comparison_id": comparison_id,
        "partner":       partner,
        "country":       country,
        "url":           url,
        "price":         price,
        "currency":      currency,
        "in_stock":      True,
        "paapi_enabled": False,  # TODO: passer à True dès que PA-API est activée (après 3 ventes)
    }
    if existing.data:
        sb.table("affiliate_links").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        sb.table("affiliate_links").insert(payload).execute()


if __name__ == "__main__":
    seed()
