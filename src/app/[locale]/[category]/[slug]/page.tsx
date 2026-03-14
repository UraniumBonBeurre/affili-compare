import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { getSiteCategories, getSiteCategory, getSiteNiche } from "@/lib/site-categories";
import { NichePageClient } from "@/components/NichePageClient";
import type { Locale, TopArticle } from "@/types/database";

interface Props {
  params: { locale: Locale; category: string; slug: string };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const cat   = getSiteCategory(params.category);
  const niche = cat ? getSiteNiche(params.category, params.slug) : null;
  if (!cat || !niche) return { title: "Not found" };
  const isEn = params.locale === "en";
  const nicheName    = isEn ? niche.name_en    : niche.name;
  const categoryName = isEn ? cat.name_en      : cat.name;
  return {
    title: `${nicheName} — ${categoryName} | MyGoodPick`,
    description: isEn
      ? `Hand-picked products and guides for ${nicheName.toLowerCase()}.`
      : `Produits et guides sélectionnés pour ${nicheName.toLowerCase()}.`,
  };
}

export function generateStaticParams() {
  const locales: Locale[] = ["fr", "en"];
  return getSiteCategories().flatMap((cat) =>
    cat.niches.flatMap((niche) =>
      locales.map((locale) => ({ locale, category: cat.id, slug: niche.slug }))
    )
  );
}

export const revalidate = 0;

export default async function NichePage({ params }: Props) {
  const { locale, category: categoryId, slug: nicheSlug } = params;

  const cat   = getSiteCategory(categoryId);
  const niche = cat ? getSiteNiche(categoryId, nicheSlug) : null;
  if (!cat || !niche) notFound();

  // Fetch products classified to this niche (populated by classification.py)
  const { data: productsRaw } = await supabase
    .from("products")
    .select("id, name, brand, image_url, price, currency, affiliate_url")
    .eq("llm_niche", nicheSlug)
    .eq("active", true)
    .order("price", { ascending: true })
    .limit(100);

  // Fetch articles whose subcategory matches niche name (FR or EN)
  const { data: articlesRaw } = await supabase
    .from("top_articles")
    .select("id, slug, title, content, pin_images, created_at")
    .or(
      `content->>subcategory.eq.${niche.name},content->>subcategory.eq.${niche.name_en}`,
    )
    .order("created_at", { ascending: false })
    .limit(24);

  const products = (productsRaw ?? []).map((p) => ({
    id:            p.id,
    name:          p.name,
    brand:         (p as { brand?: string | null }).brand ?? null,
    image_url:     p.image_url,
    price:         p.price,
    currency:      p.currency,
    affiliate_url: p.affiliate_url,
  }));

  const articles = (articlesRaw ?? []) as TopArticle[];

  return (
    <NichePageClient
      category={cat}
      niche={niche}
      products={products}
      articles={articles}
      locale={locale}
    />
  );
}
