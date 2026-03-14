"use client";

import { useState, useMemo, useCallback } from "react";
import { AiSearch } from "./AiSearch";
import { NichePanel } from "./NichePanel";
import { ProductTile } from "./ProductTile";
import { PriceRangeSlider } from "./PriceRangeSlider";
import { ArticleGrid } from "./ArticleGrid";
import { ArticlePanel } from "./ArticlePanel";
import { BodyScrollLock } from "./BodyScrollLock";
import type { SiteCategory, SiteNiche } from "@/lib/site-categories";
import type { TopArticle, Locale } from "@/types/database";

interface ProductData {
  id: string;
  name: string;
  brand: string | null;
  image_url: string | null;
  price: number | null;
  currency: string | null;
  affiliate_url: string | null;
}

interface Props {
  category: SiteCategory;
  niche: SiteNiche;
  products: ProductData[];
  articles: TopArticle[];
  locale: Locale;
}

type ArticleContentShape = {
  title_en?: string;
  intro_fr?: string;
  intro_en?: string;
  body_html_fr?: string;
  body_html_en?: string;
  month?: string;
};

function parseContent(raw: unknown): ArticleContentShape {
  if (!raw) return {};
  if (typeof raw === "string") { try { return JSON.parse(raw); } catch { return {}; } }
  return raw as ArticleContentShape;
}

export function NichePageClient({ category, niche, products, articles, locale }: Props) {
  const isEn = locale === "en";
  const labels = isEn
    ? { back: "Back", selection: "Selection", affiliate: "Affiliate links — commissions at no extra cost to you" }
    : { back: "Retour", selection: "Sélection", affiliate: "Liens affiliés — commissions sans surcoût pour vous" };

  // Price range
  const prices = products.map((p) => p.price).filter((p): p is number => p != null);
  const globalMin = prices.length ? Math.floor(Math.min(...prices)) : 0;
  const globalMax = prices.length ? Math.ceil(Math.max(...prices)) : 1000;
  const [priceRange, setPriceRange] = useState<[number, number]>([globalMin, globalMax]);

  const filteredProducts = useMemo(
    () =>
      products.filter((p) => {
        if (p.price == null) return true;
        return p.price >= priceRange[0] && p.price <= priceRange[1];
      }),
    [products, priceRange],
  );

  // Article overlay
  const [openSlug, setOpenSlug] = useState<string | null>(null);
  const openArticle = useMemo(
    () => (openSlug ? (articles.find((a) => a.slug === openSlug) ?? null) : null),
    [openSlug, articles],
  );
  const handleOpen  = useCallback((slug: string) => setOpenSlug(slug), []);
  const handleClose = useCallback(() => setOpenSlug(null), []);

  const nicheName = isEn ? niche.name_en : niche.name;
  const hasPriceSlider = prices.length > 1 && globalMin < globalMax;

  return (
    <>
      <BodyScrollLock />

      {/* Category gradient — covers the locale bg-interior.jpg */}
      <div
        className="fixed inset-0 -z-[9]"
        style={{
          background: `linear-gradient(145deg, ${category.gradient_from}, ${category.gradient_to})`,
        }}
      />

      {/* Viewport-locked flex layout — break out of layout's px-4 */}
      <div
        className="flex gap-0 overflow-hidden -mx-4"
        style={{ height: "calc(100vh - 3.5rem - 1px)" }}
      >
        {/* ── Left sidebar ── */}
        <div className="w-52 flex-shrink-0 h-full">
          <NichePanel category={category} locale={locale} />
        </div>

        {/* ── Main content ── */}
        <div className="flex-1 h-full overflow-y-auto px-5 sm:px-6 py-4 bg-black/5">

          {/* Search */}
          <div className="mb-6">
            <AiSearch locale={locale} defaultNiche={niche.slug} />
          </div>

          {/* Products */}
          <section className="mb-8">
            <div className="flex items-center justify-between gap-4 mb-4 flex-wrap">
              <h2 className="font-playfair text-xl sm:text-2xl font-bold text-white drop-shadow-sm">
                {isEn ? "Products" : "Produits"}
                <span className="ml-2 text-sm font-sans font-normal text-white/50">
                  ({filteredProducts.length})
                </span>
              </h2>
              {hasPriceSlider && (
                <PriceRangeSlider
                  min={globalMin}
                  max={globalMax}
                  value={priceRange}
                  onChange={setPriceRange}
                  locale={locale}
                />
              )}
            </div>

            {filteredProducts.length > 0 ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 sm:gap-4">
                {filteredProducts.map((p) => (
                  <ProductTile key={p.id} {...p} locale={locale} />
                ))}
              </div>
            ) : (
              <div className="bg-white/10 backdrop-blur-sm rounded-2xl border border-white/20 px-6 py-12 text-center">
                <p className="text-white/60 text-sm">
                  {isEn
                    ? `No products yet in "${nicheName}". Classification will populate this soon.`
                    : `Aucun produit pour l'instant dans "${nicheName}". La classification va bientôt alimenter cette section.`}
                </p>
              </div>
            )}
          </section>

          {/* Articles */}
          {articles.length > 0 && (
            <section className="mb-8">
              <h2 className="font-playfair text-xl sm:text-2xl font-bold text-white drop-shadow-sm mb-4">
                {isEn ? "Guides & Selections" : "Guides & Sélections"}
              </h2>
              <ArticleGrid articles={articles} locale={locale} onOpen={handleOpen} />
            </section>
          )}
        </div>
      </div>

      {/* Article overlay — rendered OUTSIDE the overflow-hidden container */}
      {openArticle &&
        (() => {
          const c          = parseContent(openArticle.content);
          const title      = isEn ? (c.title_en || openArticle.title) : openArticle.title;
          const intro      = isEn ? (c.intro_en  || c.intro_fr)       : c.intro_fr;
          const bodyHtml   = isEn ? (c.body_html_en || c.body_html_fr) : c.body_html_fr;
          const month      = c.month ?? "";
          const monthLabel = month
            ? new Date(`${month}-01`).toLocaleDateString(isEn ? "en-GB" : "fr-FR", { month: "long", year: "numeric" })
            : "";
          const dateLabel      = new Date(openArticle.created_at).toLocaleDateString(
            isEn ? "en-GB" : "fr-FR",
            { day: "numeric", month: "long", year: "numeric" },
          );
          const publishedLabel = isEn ? `Published on ${dateLabel}` : `Publié le ${dateLabel}`;

          return (
            <ArticlePanel backLabel={labels.back} onClose={handleClose}>
              <div className="max-w-4xl mx-auto px-8 pb-16 pt-4">
                <div className="mb-6">
                  <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-amber-600 bg-amber-50 px-2.5 py-1 rounded-full">
                      {labels.selection}
                    </span>
                    {monthLabel && (
                      <span className="text-xs text-stone-400 font-medium">{monthLabel}</span>
                    )}
                  </div>
                  <h1 className="font-playfair text-2xl sm:text-3xl font-semibold text-stone-900 leading-tight mb-1">
                    {title}
                  </h1>
                  <p className="text-xs text-stone-400">{publishedLabel}</p>
                </div>
                {intro && (
                  <p className="text-stone-600 text-base leading-relaxed mb-6">{intro}</p>
                )}
                {bodyHtml && (
                  <div
                    className="article-body text-stone-700 text-[15px] leading-relaxed"
                    dangerouslySetInnerHTML={{ __html: bodyHtml }}
                  />
                )}
                <p className="text-[10px] text-stone-400 text-center border-t border-stone-200 pt-4 mt-8">
                  {labels.affiliate}
                </p>
              </div>
            </ArticlePanel>
          );
        })()}
    </>
  );
}
