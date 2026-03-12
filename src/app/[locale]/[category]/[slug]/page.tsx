import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { getComparisonMeta, buildItemListSchema } from "@/lib/seo";
import { getLinksForLocale, cheapestLink } from "@/lib/affiliate-links";
import { ComparisonTable } from "@/components/ComparisonTable";
import type { Locale, ProductWithLinks, AffiliateLink } from "@/types/database";

interface Props {
  params: { locale: Locale; category: string; slug: string };
}

// ─── Data fetching ────────────────────────────────────────────────────────────

async function getComparisonData(categorySlug: string, compSlug: string) {
  const { data: category } = await supabase
    .from("categories")
    .select("*")
    .eq("slug", categorySlug)
    .single();

  if (!category) return null;

  const { data: comparison } = await supabase
    .from("comparisons")
    .select("*")
    .eq("slug", compSlug)
    .eq("category_id", category.id)
    .eq("is_published", true)
    .single();

  if (!comparison) return null;

  // Produits liés à cette comparaison (via comparison_products, triés par position)
  const { data: cpData } = await supabase
    .from("comparison_products")
    .select("position, product_id")
    .eq("comparison_id", comparison.id)
    .order("position");

  const productIds = (cpData ?? []).map((cp) => cp.product_id);

  if (!productIds.length) return { category, comparison, products: [] };

  const [productsRes, linksRes] = await Promise.all([
    supabase.from("products").select("*").in("id", productIds),
    supabase.from("affiliate_links").select("*").in("product_id", productIds).eq("comparison_id", comparison.id),
  ]);

  // Trier les produits selon comparison_products.position
  const sortedProducts = (productsRes.data ?? []).sort((a, b) => {
    const posA = cpData?.find((cp) => cp.product_id === a.id)?.position ?? 99;
    const posB = cpData?.find((cp) => cp.product_id === b.id)?.position ?? 99;
    return posA - posB;
  });

  return {
    category,
    comparison,
    products:   sortedProducts,
    links:      linksRes.data ?? [],
  };
}

// ─── Metadata ─────────────────────────────────────────────────────────────────

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const data = await getComparisonData(params.category, params.slug);
  if (!data) return { title: "Not found" };

  const meta = getComparisonMeta(data.comparison, data.category, params.locale);
  return {
    title:       meta.title,
    description: meta.description,
    alternates:  { canonical: meta.canonical },
    openGraph: {
      title:       meta.title,
      description: meta.description,
      type:        "article",
      locale:      params.locale,
    },
  };
}

export async function generateStaticParams() {
  const { data: comparisons } = await supabase
    .from("comparisons")
    .select("slug, category_id")
    .eq("is_published", true);

  const { data: categories } = await supabase.from("categories").select("id, slug");

  return (comparisons ?? []).flatMap((comp) => {
    const cat = categories?.find((c) => c.id === comp.category_id);
    if (!cat) return [];
    return (["fr", "en", "de"] as Locale[]).map((locale) => ({
      locale,
      category: cat.slug,
      slug:     comp.slug,
    }));
  });
}

export const revalidate = 86400; // ISR 24h

// ─── Page ─────────────────────────────────────────────────────────────────────

export default async function ComparisonPage({ params }: Props) {
  const { locale } = params;
  const data = await getComparisonData(params.category, params.slug);

  if (!data) notFound();

  const { category, comparison, products, links = [] } = data;

  const titleKey   = `title_${locale}` as "title_fr" | "title_en" | "title_de";
  const prosKey    = `pros_${locale}`  as "pros_fr" | "pros_en";
  const consKey    = `cons_${locale}`  as "cons_fr" | "cons_en";
  const catNameKey = `name_${locale}`  as "name_fr" | "name_en" | "name_de";

  // Enrichir les produits avec leurs liens et pros/cons localisés
  const enrichedProducts: ProductWithLinks[] = products.map((p) => {
    const productLinks = (links as AffiliateLink[]).filter((l) => l.product_id === p.id);
    const raw = p[prosKey] ?? p.pros_fr;
    const rawCons = p[consKey] ?? p.cons_fr;

    return {
      ...p,
      links:    productLinks,
      pros:     Array.isArray(raw)     ? (raw as string[])     : (JSON.parse(raw as string ?? "[]") as string[]),
      cons:     Array.isArray(rawCons) ? (rawCons as string[]) : (JSON.parse(rawCons as string ?? "[]") as string[]),
    };
  });

  const title = (comparison as Record<string, string>)[titleKey] ?? comparison.title_fr;

  // Schema.org
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://mygoodpick.com";
  const itemListSchema = buildItemListSchema(
    comparison,
    enrichedProducts.map((p) => {
      const bestLink = cheapestLink(getLinksForLocale(p.links, locale));
      return {
        name:     p.name,
        url:      `${siteUrl}/${locale}/${category.slug}/${comparison.slug}`,
        price:    bestLink?.price ?? null,
        currency: bestLink?.currency ?? "EUR",
        rating:   p.rating,
      };
    }),
    locale
  );

  return (
    <>
      {/* Schema.org JSON-LD */}
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(itemListSchema) }} />

      {/* Breadcrumb */}
      <nav className="text-sm text-gray-400 mb-6">
        <Link href={`/${locale}`} className="hover:underline">Accueil</Link>
        {" / "}
        <Link href={`/${locale}/${category.slug}`} className="hover:underline">
          {(category as Record<string, string>)[catNameKey] ?? category.name_fr}
        </Link>
        {" / "}
        <span className="text-gray-600">{title}</span>
      </nav>

      {/* Titre */}
      <h1 className="text-3xl sm:text-4xl font-extrabold text-gray-900 mb-2 leading-tight">{title}</h1>
      <p className="text-xs text-gray-400 mb-6">
        Mis à jour le {new Date(comparison.last_updated).toLocaleDateString(
          locale === "de" ? "de-DE" : locale === "en" ? "en-GB" : "fr-FR",
          { day: "2-digit", month: "long", year: "numeric" }
        )}
      </p>

      {/* Tableau comparatif */}
      <ComparisonTable products={enrichedProducts} locale={locale} />
    </>
  );
}
