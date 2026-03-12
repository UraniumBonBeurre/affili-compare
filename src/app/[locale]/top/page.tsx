import type { Metadata } from "next";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { GalleryCard } from "@/components/GalleryCard";
import type { Locale, TopArticle } from "@/types/database";

interface Props {
  params: { locale: Locale };
}

function parsePinImages(raw: unknown): string[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw as string[];
  if (typeof raw === "string") { try { return JSON.parse(raw); } catch { return []; } }
  return [];
}

function parseContent(raw: unknown): Record<string, unknown> {
  if (!raw) return {};
  if (typeof raw === "string") { try { return JSON.parse(raw); } catch { return {}; } }
  return raw as Record<string, unknown>;
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
    h1:    isEn ? "All picks" : "Toutes les sélections",
    sub:   isEn ? "Our curated product picks, updated every month." : "Nos meilleures sélections produits, mises à jour chaque mois.",
    home:  isEn ? "Home" : "Accueil",
    empty: isEn ? "No picks yet — check back soon." : "Aucune sélection pour le moment.",
  };

  // Group by month
  const byMonth = new Map<string, typeof articles>();
  for (const a of articles) {
    const c = parseContent(a.content);
    const month = (c.month as string) ?? a.created_at.slice(0, 7);
    if (!byMonth.has(month)) byMonth.set(month, []);
    byMonth.get(month)!.push(a);
  }

  return (
    <div className="py-8">
      {/* Header */}
      <div className="mb-10">
        <nav className="text-xs text-stone-400 mb-5 flex items-center gap-1.5">
          <Link href={`/${locale}`} className="hover:text-stone-700 transition-colors">{l.home}</Link>
          <span>/</span>
          <span className="text-stone-500">{l.h1}</span>
        </nav>
        <h1 className="text-3xl font-extrabold text-stone-800 mb-1">{l.h1}</h1>
        <p className="text-stone-500 text-sm">{l.sub}</p>
      </div>

      {articles.length === 0 ? (
        <p className="text-stone-400 text-center py-24">{l.empty}</p>
      ) : (
        <div className="space-y-14">
          {[...byMonth.entries()].map(([month, monthArticles]) => {
            const monthLabel = new Date(`${month}-01`).toLocaleDateString(
              isEn ? "en-GB" : "fr-FR",
              { month: "long", year: "numeric" }
            );
            return (
              <section key={month}>
                {/* Month heading */}
                <div className="flex items-center gap-3 mb-5">
                  <span className="text-xs font-bold uppercase tracking-widest text-stone-500">
                    {monthLabel}
                  </span>
                  <div className="flex-1 h-px bg-stone-200" />
                </div>

                {/* Gallery grid */}
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-4">
                  {monthArticles.map((a) => {
                    const c = parseContent(a.content);
                    const title = isEn ? ((c.title_en as string) || a.title) : a.title;
                    const subcategory = isEn
                      ? ((c.subcategory_en as string) || (c.subcategory as string))
                      : (c.subcategory as string) ?? "";
                    const pinImages = parsePinImages(a.pin_images);
                    return (
                      <GalleryCard
                        key={a.slug}
                        slug={a.slug}
                        title={title}
                        subcategory={subcategory}
                        pinImages={pinImages}
                        locale={locale}
                      />
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
