import type { Metadata } from "next";
import { AiSearch } from "@/components/AiSearch";
import { Top5Section } from "@/components/Top5Section";
import type { Locale } from "@/types/database";

interface Props {
  params: { locale: Locale };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return {
    title: "MyGoodPick — Comparez, Économisez, Achetez au meilleur prix",
    description: "Comparatifs produits indépendants avec prix en temps réel. Trouvez le meilleur prix parmi tous les marchands.",
  };
}

const HERO: Record<Locale, { h1a: string; h1b: string; sub: string }> = {
  fr: { h1a: "Comparez. Économisez.", h1b: "Achetez au meilleur prix.", sub: "Décrivez ce que vous cherchez, notre IA trouve les meilleures offres." },
  en: { h1a: "Compare. Save Money.",  h1b: "Buy at the best price.",    sub: "Describe what you're looking for, our AI finds the best deals." },
  de: { h1a: "Vergleichen. Sparen.",  h1b: "Kaufen Sie günstiger.",     sub: "Beschreiben Sie, was Sie suchen – unsere KI findet die besten Preise." },
};

export const revalidate = 3600;

export default async function HomePage({ params }: Props) {
  const { locale } = params;
  const hero = HERO[locale] ?? HERO.fr;

  return (
    <>
      {/* ── Hero ── */}
      <section className="relative text-center py-20 px-4 mb-8">
        <div className="absolute inset-0 -z-10 bg-gradient-to-b from-emerald-50/70 dark:from-emerald-950/30 to-transparent rounded-3xl" />
        <h1 className="text-4xl sm:text-5xl font-black text-gray-900 dark:text-white mb-3 leading-[1.1]">
          {hero.h1a}<br />
          <span className="text-emerald-600">{hero.h1b}</span>
        </h1>
        <p className="text-lg text-gray-500 dark:text-gray-400 max-w-md mx-auto mb-10">
          {hero.sub}
        </p>
        <AiSearch locale={locale} />
      </section>

      {/* ── Sélections du mois ── */}
      <Top5Section locale={locale} />
    </>
  );
}

