import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getSiteCategories, getSiteCategory } from "@/lib/site-categories";
import type { Locale } from "@/types/database";

interface Props {
  params: { locale: Locale; category: string };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const cat = getSiteCategory(params.category);
  if (!cat) return { title: "Not found" };
  const isEn = params.locale === "en";
  const name = isEn ? cat.name_en : cat.name;
  return {
    title: `${name} — MyGoodPick`,
    description: isEn
      ? `Explore our ${name.toLowerCase()} selections and guides.`
      : `Explorez nos sélections et guides pour la catégorie ${name}.`,
  };
}

export function generateStaticParams() {
  const locales: Locale[] = ["fr", "en"];
  return getSiteCategories().flatMap((cat) =>
    locales.map((locale) => ({ locale, category: cat.id }))
  );
}

export const revalidate = 86400;

export default function CategoryPage({ params }: Props) {
  const { locale, category: categoryId } = params;
  const cat = getSiteCategory(categoryId);
  if (!cat) notFound();

  const isEn = locale === "en";
  const name = isEn ? cat.name_en : cat.name;

  return (
    <>
      {/* Full-screen gradient background that covers the locale's bg-interior.jpg */}
      <div
        className="fixed inset-0 -z-[9]"
        style={{ background: `linear-gradient(145deg, ${cat.gradient_from}, ${cat.gradient_to})` }}
      />

      <div className="py-10 sm:py-16">
        {/* Back link */}
        <Link
          href={`/${locale}`}
          className="inline-flex items-center gap-1.5 text-white/60 hover:text-white text-sm mb-8 transition-colors group"
        >
          <span className="group-hover:-translate-x-0.5 transition-transform">←</span>
          <span>{isEn ? "All categories" : "Toutes les catégories"}</span>
        </Link>

        {/* Hero */}
        <div className="text-center mb-12">
          <div className="text-6xl sm:text-7xl mb-4 drop-shadow-lg">{cat.icon}</div>
          <h1 className="font-playfair text-3xl sm:text-5xl font-bold text-white drop-shadow mb-3">
            {name}
          </h1>
          <p className="text-white/60 text-sm sm:text-base max-w-md mx-auto">
            {isEn
              ? `Discover our hand-picked selections in ${name.toLowerCase()}`
              : `Découvrez nos sélections dans ${name.toLowerCase()}`}
          </p>
        </div>

        {/* Niches grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-4">
          {cat.niches.map((niche) => (
            <Link
              key={niche.slug}
              href={`/${locale}/${categoryId}/${niche.slug}`}
              className="group bg-white/10 hover:bg-white/20 backdrop-blur-sm border border-white/20 hover:border-white/40 rounded-2xl px-4 py-5 flex items-center gap-3 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg"
            >
              <div className="flex-1 min-w-0">
                <span className="font-medium text-white text-sm sm:text-base leading-tight line-clamp-2 group-hover:text-white/90">
                  {isEn ? niche.name_en : niche.name}
                </span>
              </div>
              <span className="text-white/40 group-hover:text-white/70 flex-shrink-0 transition-colors text-sm">→</span>
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}
