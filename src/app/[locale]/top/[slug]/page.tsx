import type { Metadata } from "next";
import Link from "next/link";
import Image from "next/image";
import { notFound } from "next/navigation";
import { supabase } from "@/lib/supabase";
import type { Locale } from "@/types/database";

interface TopProduct {
  id?: string;
  name: string;
  brand: string | null;
  price: number | null;
  url: string | null;
  image_url: string | null;
  blurb_fr: string;
}

interface ArticleContent {
  category_slug?: string;
  subcategory?: string;
  keyword?: string;
  title_en?: string;
  intro_fr?: string;
  intro_en?: string;
  products?: TopProduct[];
  month?: string;
}

interface Props {
  params: { locale: Locale; slug: string };
}

// ─── Data fetching ─────────────────────────────────────────────────────────────

async function getArticle(slug: string) {
  const { data } = await supabase
    .from("top_articles")
    .select("id, slug, url, title, content, pin_images, created_at")
    .eq("slug", slug)
    .single();
  return data;
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

  const c = parseContent(article.content as string | Record<string, unknown> | null);
  const isEn = params.locale === "en";
  const title = isEn ? (c.title_en || article.title) : article.title;
  const intro = isEn ? (c.intro_en || c.intro_fr) : c.intro_fr;

  return {
    title,
    description: intro?.slice(0, 160) ?? undefined,
    alternates: {
      canonical: `${process.env.NEXT_PUBLIC_SITE_URL ?? "https://mygoodpick.com"}/${params.locale}/top/${params.slug}`,
    },
  };
}

export const revalidate = 3600;

// ─── Page ──────────────────────────────────────────────────────────────────────

export default async function TopArticlePage({ params }: Props) {
  const { locale, slug } = params;
  const article = await getArticle(slug);
  if (!article) notFound();

  const c = parseContent(article.content as string | Record<string, unknown> | null);
  const isEn = locale === "en";

  const title    = isEn ? (c.title_en || article.title) : article.title;
  const intro    = isEn ? (c.intro_en || c.intro_fr) : c.intro_fr;
  const products = c.products ?? [];
  const month    = c.month ?? "";

  const monthLabel = month
    ? new Date(`${month}-01`).toLocaleDateString(
        locale === "en" ? "en-GB" : "fr-FR",
        { month: "long", year: "numeric" }
      )
    : "";

  const pinImages = parsePinImages(article.pin_images as string | string[] | null);
  const heroImage = pinImages[0] ?? null;

  const labels = {
    fr: { back: "← Retour aux sélections", offer: "Voir l'offre →", selection: "Sélection" },
    en: { back: "← Back to selections",    offer: "See the deal →", selection: "Selection"  },
    de: { back: "← Zurück",                offer: "Zum Angebot →",  selection: "Auswahl"    },
  };
  const l = labels[locale] ?? labels.fr;

  return (
    <>
      {/* Breadcrumb */}
      <nav className="text-sm text-gray-400 mb-6 flex items-center gap-1.5 flex-wrap">
        <Link href={`/${locale}`} className="hover:text-emerald-600 transition-colors">Accueil</Link>
        <span>/</span>
        <Link href={`/${locale}/top`} className="hover:text-emerald-600 transition-colors">Sélections</Link>
        <span>/</span>
        <span className="text-gray-600 dark:text-gray-300 line-clamp-1">{title}</span>
      </nav>

      {/* Hero image (pin visuel) */}
      {heroImage && (
        <div className="w-full max-h-80 rounded-2xl overflow-hidden mb-8 relative bg-gray-100 dark:bg-gray-800">
          <Image
            src={heroImage}
            alt={title}
            width={900}
            height={506}
            className="w-full h-full object-cover"
            priority
          />
        </div>
      )}

      {/* Article header */}
      <div className="mb-8">
        <p className="text-xs text-emerald-600 dark:text-emerald-400 font-semibold uppercase tracking-wide mb-2">
          {l.selection} — {monthLabel}
        </p>
        <h1 className="text-3xl sm:text-4xl font-extrabold text-gray-900 dark:text-white leading-tight mb-4">
          {title}
        </h1>
        {intro && (
          <p className="text-gray-600 dark:text-gray-300 text-base leading-relaxed max-w-2xl">
            {intro}
          </p>
        )}
      </div>

      {/* Product list */}
      {products.length > 0 && (
        <div className="space-y-4 mb-12">
          {products.map((p, i) => (
            <div
              key={p.id ?? i}
              className="flex gap-4 p-5 rounded-2xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 shadow-sm hover:shadow-md transition-shadow"
            >
              {/* Rank badge */}
              <div className="shrink-0 w-8 h-8 flex items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-900 text-emerald-700 dark:text-emerald-400 font-extrabold text-sm mt-1">
                {i + 1}
              </div>

              {/* Product image */}
              {p.image_url && (
                <div className="shrink-0 w-20 h-20 rounded-xl overflow-hidden bg-gray-50 dark:bg-gray-800 relative">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={p.image_url}
                    alt={p.name}
                    className="w-full h-full object-contain"
                    loading="lazy"
                  />
                </div>
              )}

              {/* Info */}
              <div className="flex-1 min-w-0">
                {p.brand && (
                  <p className="text-xs text-gray-400 dark:text-gray-500 mb-0.5">{p.brand}</p>
                )}
                <p className="font-semibold text-gray-900 dark:text-white leading-snug mb-1 line-clamp-2">
                  {p.name}
                </p>
                {p.blurb_fr && (
                  <p className="text-sm text-gray-500 dark:text-gray-400 leading-relaxed mb-3">
                    {p.blurb_fr}
                  </p>
                )}
                <div className="flex items-center gap-3 flex-wrap">
                  {p.price != null && (
                    <span className="text-lg font-bold text-emerald-600 dark:text-emerald-400">
                      {p.price.toFixed(2)} €
                    </span>
                  )}
                  {p.url && (
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noopener noreferrer nofollow sponsored"
                      className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 text-white text-sm font-semibold transition-colors"
                    >
                      {l.offer}
                    </a>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Footer nav */}
      <div className="border-t border-gray-100 dark:border-gray-800 pt-6 flex items-center justify-between">
        <Link
          href={`/${locale}/top`}
          className="text-sm text-gray-400 hover:text-emerald-600 transition-colors"
        >
          {l.back}
        </Link>
        <span className="text-xs text-gray-300 dark:text-gray-600">mygoodpick.com</span>
      </div>
    </>
  );
}
