import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { getCategoryMeta } from "@/lib/seo";
import { SITE_CATEGORIES } from "@/config/categories";
import type { Locale } from "@/types/database";

interface Props {
  params: { locale: Locale; category: string };
}

// ─── Data fetching ────────────────────────────────────────────────────────────
async function getCategoryData(slug: string) {
  // 1. Config is the source of truth for valid category slugs
  const configCat = SITE_CATEGORIES.find((c) => c.slug === slug) ?? null;
  if (!configCat) return null; // unknown slug → let Next.js 404

  // 2. maybeSingle() never throws on empty — returns data: null instead
  const catRes = await supabase
    .from("categories")
    .select("*")
    .eq("slug", slug)
    .maybeSingle();

  const dbCategory = catRes.data ?? null;

  // 3. Comparisons filtered at DB level (category_id filter) — no client-side filtering
  const comparisons = dbCategory
    ? (
        await supabase
          .from("comparisons")
          .select("id, slug, title_fr, title_en, title_de, last_updated, subcategory")
          .eq("category_id", dbCategory.id)
          .eq("is_published", true)
          .order("last_updated", { ascending: false })
      ).data ?? []
    : [];

  return { dbCategory, configCat, comparisons };
}

// ─── Metadata ─────────────────────────────────────────────────────────────────
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { category, locale } = params;
  const data = await getCategoryData(category);
  if (!data) return { title: "Not found" };

  // Use DB category for SEO helpers if available, else build a minimal stub
  const cat = data.dbCategory ?? {
    slug: data.configCat.slug,
    name_fr: data.configCat.nameFr,
    name_en: data.configCat.nameEn,
    name_de: data.configCat.nameFr,
    icon: data.configCat.icon,
    is_active: true,
  };
  const meta = getCategoryMeta(cat as Parameters<typeof getCategoryMeta>[0], locale);
  return {
    title: meta.title,
    description: meta.description,
    alternates: { canonical: meta.canonical },
  };
}

// ─── Static params — driven by SITE_CATEGORIES, not DB ───────────────────────
// This ensures every known category has a pre-built route regardless of DB state
export async function generateStaticParams() {
  return SITE_CATEGORIES.flatMap((cat) =>
    (["fr", "en", "de"] as Locale[]).map((locale) => ({
      locale,
      category: cat.slug,
    }))
  );
}

export const revalidate = 3600;

// ─── Page ──────────────────────────────────────────────────────────────────────
export default async function CategoryPage({ params }: Props) {
  const { locale, category: categorySlug } = params;
  const data = await getCategoryData(categorySlug);

  if (!data) notFound(); // slug not in SITE_CATEGORIES — truly unknown

  const { dbCategory, configCat, comparisons } = data!;

  const nameKey  = `name_${locale}`  as "name_fr" | "name_en" | "name_de";
  const titleKey = `title_${locale}` as "title_fr" | "title_en" | "title_de";

  // Display name: prefer DB row, fall back to config
  const displayName = dbCategory
    ? (dbCategory[nameKey] ?? dbCategory.name_fr)
    : locale === "en"
    ? configCat.nameEn
    : configCat.nameFr;
  const displayIcon = dbCategory?.icon ?? configCat.icon;

  // Group comparisons by subcategory
  const groups = new Map<string, typeof comparisons>();
  for (const comp of comparisons) {
    const sub = (comp as Record<string, string>).subcategory || "";
    if (!groups.has(sub)) groups.set(sub, []);
    groups.get(sub)!.push(comp);
  }

  return (
    <>
      {/* Breadcrumb + title */}
      <div className="mb-8">
        <p className="text-sm text-gray-400 mb-2">
          <Link href={`/${locale}`} className="hover:underline">Accueil</Link>
          {" / "}
          {displayName}
        </p>
        <h1 className="text-3xl font-extrabold text-gray-900">
          {displayIcon} {displayName}
        </h1>
      </div>

      {/* Empty state */}
      {comparisons.length === 0 && (
        <div className="mt-12 text-center py-16 rounded-2xl bg-white border border-gray-100 shadow-sm">
          <p className="text-4xl mb-4">{displayIcon}</p>
          <h2 className="text-lg font-bold text-gray-700 mb-2">
            Bientôt disponible
          </h2>
          <p className="text-sm text-gray-400 max-w-xs mx-auto">
            Nos comparatifs pour &ldquo;{displayName}&rdquo; arrivent prochainement.
          </p>
          <Link
            href={`/${locale}`}
            className="inline-block mt-6 px-4 py-2 bg-emerald-600 text-white text-sm font-semibold rounded-lg hover:bg-emerald-700 transition-colors"
          >
            ← Retour à l&apos;accueil
          </Link>
        </div>
      )}

      {/* Comparisons grid, grouped by subcategory */}
      {Array.from(groups.entries()).map(([sub, comps]) => (
        <section key={sub || "_"} className="mb-10">
          {sub && (
            <h2 className="text-lg font-bold text-gray-700 mb-4 pb-2 border-b border-gray-100">
              {sub}
            </h2>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {comps.map((comp) => (
              <Link
                key={comp.id}
                href={`/${locale}/${categorySlug}/${comp.slug}`}
                className="block p-5 rounded-2xl bg-white border border-gray-100 shadow-sm hover:shadow-md hover:border-emerald-300 transition-all group"
              >
                <h3 className="font-bold text-gray-900 text-sm leading-snug group-hover:text-emerald-700 transition-colors">
                  {(comp as Record<string, string>)[titleKey] ?? comp.title_fr}
                </h3>
                <p className="text-xs text-gray-400 mt-2">
                  Mis à jour le{" "}
                  {new Date(comp.last_updated).toLocaleDateString(
                    locale === "de" ? "de-DE" : locale === "en" ? "en-GB" : "fr-FR",
                    { day: "2-digit", month: "long", year: "numeric" }
                  )}
                </p>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
