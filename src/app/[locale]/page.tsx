import type { Metadata } from "next";
import { CategoryCard } from "@/components/CategoryCard";
import { getSiteCategories } from "@/lib/site-categories";
import type { Locale } from "@/types/database";

interface Props {
  params: { locale: Locale };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const isEn = params.locale === "en";
  return {
    title: isEn
      ? "MyGoodPick — Your Multi-Category Shopping Guide"
      : "MyGoodPick — Guide d'achat multi-catégories",
    description: isEn
      ? "Independent product selections across beauty, tech, home, sport and more."
      : "Sélections produits indépendantes — beauté, tech, maison, sport et plus encore.",
  };
}

export default function HomePage({ params }: Props) {
  const { locale } = params;
  const categories = getSiteCategories();
  const isEn = locale === "en";

  return (
    <div className="py-8 sm:py-12">
      {/* Header */}
      <div className="text-center mb-8 sm:mb-10">
        <h1 className="font-playfair text-3xl sm:text-4xl font-bold text-stone-800 mb-2">
          {isEn ? "What are you looking for?" : "Que cherchez-vous ?"}
        </h1>
        <p className="text-stone-500 text-sm">
          {isEn
            ? "Explore our curated selections by category"
            : "Explorez nos sélections par catégorie"}
        </p>
      </div>

      {/* Category grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 sm:gap-4">
        {categories.map((cat) => (
          <CategoryCard
            key={cat.id}
            id={cat.id}
            name={isEn ? cat.name_en : cat.name}
            icon={cat.icon}
            gradientFrom={cat.gradient_from}
            gradientTo={cat.gradient_to}
            locale={locale}
          />
        ))}
      </div>
    </div>
  );
}
