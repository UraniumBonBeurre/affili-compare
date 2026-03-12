import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { ArticlePanel } from "@/components/ArticlePanel";
import type { Locale, TopArticle } from "@/types/database";

interface TopProduct {
  id?: string;
  name: string;
  brand: string | null;
  price: number | null;
  url: string | null;
  image_url: string | null;
  blurb_fr?: string;
}

interface ArticleContent {
  category_slug?: string;
  subcategory?: string;
  keyword?: string;
  title_en?: string;
  intro_fr?: string;
  intro_en?: string;
  body_html_fr?: string;
  body_html_en?: string;
  products?: TopProduct[];
  month?: string;
}

interface Props {
  params: { locale: Locale; slug: string };
}

// ─── Data fetching ─────────────────────────────────────────────────────────────

async function getArticle(slug: string): Promise<TopArticle | null> {
  const { data } = await supabase
    .from("top_articles")
    .select("id, slug, url, title, content, pin_images, created_at")
    .eq("slug", slug)
    .single();
  return data as TopArticle | null;
}

function parseContent(raw: string | Record<string, unknown> | null): ArticleContent {
  if (!raw) return {};
  if (typeof raw === "string") {
    try { return JSON.parse(raw) as ArticleContent; } catch { return {}; }
  }
  return raw as ArticleContent;
}

function parsePinImages(raw: string | string[] | null): string[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw;
  try { return JSON.parse(raw) as string[]; } catch { return []; }
}

// ─── Metadata ─────────────────────────────────────────────────────────────────

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const article = await getArticle(params.slug);
  if (!article) return { title: "Not found" };

  const c    = parseContent(article.content as string | Record<string, unknown> | null);
  const isEn = params.locale === "en";
  const title = isEn ? (c.title_en || article.title) : article.title;
  const intro = isEn ? (c.intro_en || c.intro_fr) : c.intro_fr;

  return {
    title,
    description: intro?.slice(0, 160) ?? undefined,
    alternates: {
      canonical: `https://mygoodpick.com/${params.locale}/top/${params.slug}`,
    },
  };
}

export const revalidate = 0;

// ─── Page ──────────────────────────────────────────────────────────────────────

export default async function TopArticlePage({ params }: Props) {
  const { locale, slug } = params;
  const article = await getArticle(slug);
  if (!article) notFound();

  const c        = parseContent(article.content as string | Record<string, unknown> | null);
  const isEn     = locale === "en";
  const title    = isEn ? (c.title_en || article.title) : article.title;
  const intro    = isEn ? (c.intro_en || c.intro_fr) : c.intro_fr;
  const bodyHtml = isEn ? (c.body_html_en || c.body_html_fr) : c.body_html_fr;
  const products = c.products ?? [];
  const month    = c.month ?? "";

  const monthLabel = month
    ? new Date(`${month}-01`).toLocaleDateString(
        isEn ? "en-GB" : "fr-FR",
        { month: "long", year: "numeric" }
      )
    : "";

  const publishedAt = new Date(article.created_at);
  const dateLabel   = publishedAt.toLocaleDateString(
    isEn ? "en-GB" : "fr-FR",
    { day: "numeric", month: "long", year: "numeric" }
  );

  // First usable image URL (http = R2, / = public folder)
  const pinImages = parsePinImages(article.pin_images as string | string[] | null);
  const bgImage   = pinImages.find((u) => u.startsWith("http") || u.startsWith("/")) ?? null;

  const l = isEn
    ? {
        back:      "Back to picks",
        offer:     "See deal →",
        selection: "Selection",
        published: `Published on ${dateLabel}`,
        ourPicks:  `Our picks${monthLabel ? ` — ${monthLabel}` : ""}`,
        affiliate: "Affiliate links — commissions at no extra cost to you",
      }
    : {
        back:      "Retour aux sélections",
        offer:     "Voir l'offre →",
        selection: "Sélection",
        published: `Publié le ${dateLabel}`,
        ourPicks:  `Notre sélection${monthLabel ? ` — ${monthLabel}` : ""}`,
        affiliate: "Liens affiliés — commissions sans surcoût pour vous",
      };

  return (
    <ArticlePanel bgImage={bgImage} backLabel={l.back}>
      <div className="max-w-2xl mx-auto px-4 pb-16 pt-4">

        {/* Title block */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <span className="text-[10px] font-bold uppercase tracking-widest text-stone-400 bg-stone-200/60 px-2.5 py-1 rounded-full">
              {l.selection}
            </span>
            {monthLabel && (
              <span className="text-xs text-stone-400 font-medium">{monthLabel}</span>
            )}
          </div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-stone-900 leading-tight mb-1">
            {title}
          </h1>
          <p className="text-xs text-stone-400">{l.published}</p>
        </div>

        {/* Intro text */}
        {intro && (
          <p className="text-stone-600 text-base leading-relaxed mb-6">
            {intro}
          </p>
        )}

        {/* Rich HTML article body */}
        {bodyHtml && (
          <div
            className="article-body text-stone-700 text-[15px] leading-relaxed"
            dangerouslySetInnerHTML={{ __html: bodyHtml }}
          />
        )}

        {/* Affiliate disclaimer */}
        <p className="text-[10px] text-stone-400 text-center border-t border-stone-200 pt-4 mt-8">
          {l.affiliate}
        </p>
      </div>
    </ArticlePanel>
  );
}

