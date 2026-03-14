import type { Metadata } from "next";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { TopGallery } from "@/components/TopGallery";
import type { Locale, TopArticle } from "@/types/database";

interface Props {
  params: { locale: Locale };
}

async function getArticles(): Promise<TopArticle[]> {
  const { data } = await supabase
    .from("top_articles")
    .select("id, slug, title, content, pin_images, created_at")
    .order("created_at", { ascending: false })
    .limit(50);
  return (data as TopArticle[] | null) ?? [];
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return {
    title: params.locale === "en" ? "Monthly picks — MyGoodPick" : "Sélections du mois — MyGoodPick",
  };
}

export const revalidate = 0;

export default async function TopListingPage({ params }: Props) {
  const { locale } = params;
  const articles = await getArticles();
  const isEn = locale === "en";

  const l = {
    home:  isEn ? "Home" : "Accueil",
    picks: isEn ? "Our picks" : "Nos incontournables",
    empty: isEn ? "No picks yet — check back soon." : "Aucune sélection pour le moment.",
  };

  return (
    <div className="py-8">
      {/* Breadcrumb */}
      <nav className="text-xs text-stone-400 mb-8 flex items-center gap-1.5">
        <Link href={`/${locale}`} className="hover:text-stone-700 transition-colors">{l.home}</Link>
        <span>/</span>
        <span className="text-stone-500">{l.picks}</span>
      </nav>

      {articles.length === 0 ? (
        <p className="text-stone-400 text-center py-24">{l.empty}</p>
      ) : (
        <TopGallery articles={articles} locale={locale} />
      )}
    </div>
  );
}
