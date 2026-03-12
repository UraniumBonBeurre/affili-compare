import type { Comparison, Category, Locale } from "@/types/database";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://mygoodpick.com";
const CURRENT_YEAR = new Date().getFullYear();

interface SeoMeta {
  title:       string;
  description: string;
  canonical:   string;
  ogImage?:    string;
}

/** Métadonnées pour une page comparatif */
export function getComparisonMeta(
  comparison: Comparison,
  category: Category,
  locale: Locale
): SeoMeta {
  const titles:  Record<Locale, string | null> = { fr: comparison.title_fr, en: comparison.title_en, de: comparison.title_de };
  const descs:   Record<Locale, string | null> = { fr: category.meta_description_fr, en: category.meta_description_en, de: category.meta_description_de };

  const title       = titles[locale] ?? comparison.title_fr;
  const description = (descs[locale] ?? descs.fr ?? "").slice(0, 155);
  const canonical   = `${SITE_URL}/${locale}/${category.slug}/${comparison.slug}`;

  return { title, description, canonical };
}

/** Métadonnées pour une page catégorie */
export function getCategoryMeta(category: Category, locale: Locale): SeoMeta {
  const names: Record<Locale, string | null> = { fr: category.name_fr, en: category.name_en, de: category.name_de };
  const descs: Record<Locale, string | null> = { fr: category.meta_description_fr, en: category.meta_description_en, de: category.meta_description_de };

  const name        = names[locale] ?? category.name_fr;
  const title       = `${name} – Comparatif ${CURRENT_YEAR} | MyGoodPick`;
  const description = (descs[locale] ?? descs.fr ?? "").slice(0, 155);
  const canonical   = `${SITE_URL}/${locale}/${category.slug}`;

  return { title, description, canonical };
}

/** Schema.org ItemList pour un comparatif */
export function buildItemListSchema(
  comparison: Comparison,
  products: { name: string; url: string; price: number | null; currency: string }[],
  locale: Locale
) {
  const titles: Record<Locale, string | null> = { fr: comparison.title_fr, en: comparison.title_en, de: comparison.title_de };
  return {
    "@context": "https://schema.org",
    "@type":    "ItemList",
    name:       titles[locale] ?? comparison.title_fr,
    itemListElement: products.map((p, i) => ({
      "@type":    "ListItem",
      position:   i + 1,
      name:       p.name,
      url:        p.url,
      ...(p.price && {
        offers: {
          "@type":         "Offer",
          price:           p.price,
          priceCurrency:   p.currency,
          availability:    "https://schema.org/InStock",
        },
      }),
    })),
  };
}

/** Schema.org FAQPage */
export function buildFaqSchema(faq: { question: string; answer: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type":    "FAQPage",
    mainEntity: faq.map((item) => ({
      "@type":          "Question",
      name:             item.question,
      acceptedAnswer:   { "@type": "Answer", text: item.answer },
    })),
  };
}
