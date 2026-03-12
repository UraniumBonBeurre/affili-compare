import type { Metadata } from "next";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import type { Locale } from "@/types/database";

interface Props {
  params: { locale: Locale };
}

interface ArticleContent {
  category_slug?: string;
  subcategory?: string;
  title_en?: string;
  intro_fr?: string;
  intro_en?: string;
  month?: string;
}

function parseContent(raw: string | Record<string, unknown> | null): ArticleContent {
  if (!raw) return {};
  if (typeof raw === "string") {
    try { return JSON.parse(raw) as ArticleContent; } catch { return {}; }
  }
  return raw as ArticleContent;
}

async function getArticles() {
  const { data } = await supabase
    .from("top_articles")
    .select("id, slug, title, content, created_at")
    .order("created_at", { ascending: false })
    .limit(50);
  return data ?? [];
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const titles = {
    fr: "Sélections du mois — MyGoodPick",
    en: "Monthly picks — MyGoodPick",
    de: "Monatsauswahl — MyGoodPick",
  };
  return { title: titles[params.locale] ?? titles.fr };
}

export const revalidate = 3600;

export default async function TopListingPage({ params }: Props) {
  const { locale } = params;
  const articles = await getArticles();

  const isEn = locale === "en";

  const labels = {
    fr: { h1: "Sélections du mois", sub: "Nos meilleurs choix produits, mis à jour chaque mois.", read: "Lire →" },
    en: { h1: "Monthly picks",      sub: "Our best product picks, updated every month.",           read: "Read →" },
    de: { h1: "Monatsauswahl",       sub: "Unsere besten Produktempfehlungen, monatlich aktualisiert.", read: "Lesen →" },
  };
  const l = labels[locale] ?? labels.fr;

  // Group by month
  const byMonth = new Map<string, typeof articles>();
  for (const a of articles) {
    const c = parseContent(a.content as string | Record<string, unknown> | null);
    const month = c.month ?? a.created_at.slice(0, 7);
    if (!byMonth.has(month)) byMonth.set(month, []);
    byMonth.get(month)!.push(a);
  }

  return (
    <>
      {/* Header */}
      <div className="mb-10">
        <nav className="text-sm text-gray-400 mb-4 flex items-center gap-1.5">
          <Link href={`/${locale}`} className="hover:text-emerald-600 transition-colors">Accueil</Link>
          <span>/</span>
          <span className="text-gray-600 dark:text-gray-300">{l.h1}</span>
        </nav>
        <h1 className="text-3xl font-extrabold text-gray-900 dark:text-white mb-2">{l.h1}</h1>
        <p className="text-gray-500 dark:text-gray-400">{l.sub}</p>
      </div>

      {/* Articles grouped by month */}
      {articles.length === 0 ? (
        <p className="text-gray-400 text-center py-20">Aucune sélection pour le moment.</p>
      ) : (
        <div className="space-y-12">
          {[...byMonth.entries()].map(([month, monthArticles]) => {
            const monthLabel = new Date(`${month}-01`).toLocaleDateString(
              locale === "en" ? "en-GB" : "fr-FR",
              { month: "long", year: "numeric" }
            );
            return (
              <section key={month}>
                <h2 className="text-xs font-bold uppercase tracking-widest text-emerald-600 dark:text-emerald-400 mb-4">
                  {monthLabel}
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {monthArticles.map((a) => {
                    const c = parseContent(a.content as string | Record<string, unknown> | null);
                    const title = isEn ? (c.title_en || a.title) : a.title;
                    const intro = isEn ? (c.intro_en || c.intro_fr) : c.intro_fr;
                    return (
                      <Link
                        key={a.slug}
                        href={`/${locale}/top/${a.slug}`}
                        className="flex flex-col gap-2 p-5 rounded-2xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 shadow-sm hover:shadow-md hover:border-emerald-300 dark:hover:border-emerald-700 transition-all group"
                      >
                        {c.subcategory && (
                          <span className="text-xs text-gray-400 dark:text-gray-500">{c.subcategory}</span>
                        )}
                        <p className="font-semibold text-gray-900 dark:text-white leading-snug line-clamp-2 group-hover:text-emerald-700 dark:group-hover:text-emerald-400 transition-colors">
                          {title}
                        </p>
                        {intro && (
                          <p className="text-sm text-gray-500 dark:text-gray-400 line-clamp-2">{intro}</p>
                        )}
                        <span className="mt-auto text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                          {l.read}
                        </span>
                      </Link>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </>
  );
}
