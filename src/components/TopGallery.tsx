"use client";

import { useState, useMemo, useCallback } from "react";
import { GalleryCard } from "./GalleryCard";
import { ArticlePanel } from "./ArticlePanel";
import type { TopArticle, Locale } from "@/types/database";

interface ArticleContent {
  title_en?: string;
  subcategory?: string;
  subcategory_en?: string;
  intro_fr?: string;
  intro_en?: string;
  body_html_fr?: string;
  body_html_en?: string;
  month?: string;
}

interface Props {
  articles: TopArticle[];
  locale: Locale;
}

function parseContent(raw: unknown): ArticleContent {
  if (!raw) return {};
  if (typeof raw === "string") { try { return JSON.parse(raw); } catch { return {}; } }
  return raw as ArticleContent;
}

function parsePinImages(raw: unknown): string[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw as string[];
  if (typeof raw === "string") { try { return JSON.parse(raw); } catch { return []; } }
  return [];
}

// Mosaic pattern — repeating group of 6 cards on a grid-cols-6 base:
//   Row A: [0] big wide (4 col 16:9)  +  [1] small (2 col 4:3)
//   Row B: [2] small   (2 col square) +  [3] big wide (4 col 16:9)
//   Row C: [4] medium  (3 col 4:3)    +  [5] medium (3 col 4:3)
function getMosaicClasses(indexInMonth: number): { col: string; aspect: string } {
  switch (indexInMonth % 6) {
    case 0: return { col: "col-span-4", aspect: "aspect-[16/9]" };
    case 1: return { col: "col-span-2", aspect: "aspect-[4/3]" };
    case 2: return { col: "col-span-2", aspect: "aspect-square" };
    case 3: return { col: "col-span-4", aspect: "aspect-[16/9]" };
    case 4: return { col: "col-span-3", aspect: "aspect-[4/3]" };
    default: return { col: "col-span-3", aspect: "aspect-[4/3]" };
  }
}

export function TopGallery({ articles, locale }: Props) {
  const [openSlug,    setOpenSlug]    = useState<string | null>(null);
  const [filterNiche, setFilterNiche] = useState<string>("all");
  const isEn = locale === "en";

  const labels = isEn
    ? { back: "Back to picks", selection: "Selection", affiliate: "Affiliate links — commissions at no extra cost to you" }
    : { back: "Retour",        selection: "Sélection",  affiliate: "Liens affiliés — commissions sans surcoût pour vous" };

  // Unique subcategories for the dropdown
  const niches = useMemo(() => {
    const set = new Set<string>();
    for (const a of articles) {
      const c = parseContent(a.content);
      const sub = isEn ? (c.subcategory_en || c.subcategory) : c.subcategory;
      if (sub) set.add(sub);
    }
    return [...set].sort();
  }, [articles, isEn]);

  // Filter then group by month
  const byMonth = useMemo(() => {
    const filtered = filterNiche === "all"
      ? articles
      : articles.filter((a) => {
          const c   = parseContent(a.content);
          const sub = isEn ? (c.subcategory_en || c.subcategory) : c.subcategory;
          return sub === filterNiche;
        });

    const map = new Map<string, TopArticle[]>();
    for (const a of filtered) {
      const c     = parseContent(a.content);
      const month = (c.month as string) ?? a.created_at.slice(0, 7);
      if (!map.has(month)) map.set(month, []);
      map.get(month)!.push(a);
    }
    return [...map.entries()];
  }, [articles, filterNiche, isEn]);

  const openArticle = useMemo(
    () => (openSlug ? (articles.find((a) => a.slug === openSlug) ?? null) : null),
    [openSlug, articles],
  );

  const handleOpen  = useCallback((slug: string) => setOpenSlug(slug), []);
  const handleClose = useCallback(() => setOpenSlug(null), []);

  return (
    <>
      {/* ── "Nos incontournables pour [niche]" ── */}
      <div className="mb-10 flex items-baseline gap-3 flex-wrap">
        <h1 className="font-playfair text-3xl sm:text-4xl font-semibold text-amber-800 leading-tight">
          {isEn ? "Our must-haves for" : "Nos incontournables pour"}
        </h1>
        <div className="relative">
          <select
            value={filterNiche}
            onChange={(e) => setFilterNiche(e.target.value)}
            className="appearance-none font-playfair font-semibold text-2xl sm:text-3xl text-amber-700 bg-amber-50 hover:bg-amber-100 border border-amber-200 rounded-xl px-4 py-1 pr-9 cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-amber-300 leading-tight"
          >
            <option value="all">{isEn ? "all categories" : "toutes les niches"}</option>
            {niches.map((niche) => (
              <option key={niche} value={niche}>{niche}</option>
            ))}
          </select>
          {/* Custom dropdown arrow */}
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-amber-500 text-sm">▾</span>
        </div>
      </div>

      {/* ── Mosaic grid, grouped by month ── */}
      <div className="space-y-14">
        {byMonth.map(([month, monthArticles]) => {
          const monthLabel = new Date(`${month}-01`).toLocaleDateString(
            isEn ? "en-GB" : "fr-FR",
            { month: "long", year: "numeric" },
          );
          return (
            <section key={month}>
              <div className="flex items-center gap-3 mb-5">
                <span className="font-playfair text-sm font-semibold text-stone-500 italic">
                  {monthLabel}
                </span>
                <div className="flex-1 h-px bg-stone-200" />
              </div>

              <div className="grid grid-cols-6 gap-3 sm:gap-4">
                {monthArticles.map((a, idx) => {
                  const c           = parseContent(a.content);
                  const title       = isEn ? ((c.title_en as string) || a.title) : a.title;
                  const subcategory = isEn
                    ? ((c.subcategory_en as string) || (c.subcategory as string) || "")
                    : ((c.subcategory as string) ?? "");
                  const pinImages   = parsePinImages(a.pin_images);
                  const { col, aspect } = getMosaicClasses(idx);
                  return (
                    <div key={a.slug} className={col}>
                      <GalleryCard
                        slug={a.slug}
                        title={title}
                        subcategory={subcategory}
                        pinImages={pinImages}
                        locale={locale}
                        onOpen={handleOpen}
                        aspectClass={aspect}
                      />
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}

        {byMonth.length === 0 && (
          <p className="text-stone-400 text-center py-20">
            {isEn ? "No picks in this category yet." : "Aucune sélection dans cette niche pour le moment."}
          </p>
        )}
      </div>

      {/* ── Article overlay ── */}
      {openArticle && (() => {
        const c         = parseContent(openArticle.content);
        const title     = isEn ? (c.title_en || openArticle.title) : openArticle.title;
        const intro     = isEn ? (c.intro_en  || c.intro_fr)       : c.intro_fr;
        const bodyHtml  = isEn ? (c.body_html_en || c.body_html_fr) : c.body_html_fr;
        const month     = c.month ?? "";
        const monthLabel = month
          ? new Date(`${month}-01`).toLocaleDateString(isEn ? "en-GB" : "fr-FR", { month: "long", year: "numeric" })
          : "";
        const dateLabel      = new Date(openArticle.created_at).toLocaleDateString(isEn ? "en-GB" : "fr-FR", { day: "numeric", month: "long", year: "numeric" });
        const publishedLabel = isEn ? `Published on ${dateLabel}` : `Publié le ${dateLabel}`;

        return (
          <ArticlePanel backLabel={labels.back} onClose={handleClose}>
            <div className="max-w-4xl mx-auto px-8 pb-16 pt-4">
              <div className="mb-6">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-amber-600 bg-amber-50 px-2.5 py-1 rounded-full">
                    {labels.selection}
                  </span>
                  {monthLabel && <span className="text-xs text-stone-400 font-medium">{monthLabel}</span>}
                </div>
                <h1 className="font-playfair text-2xl sm:text-3xl font-semibold text-stone-900 leading-tight mb-1">
                  {title}
                </h1>
                <p className="text-xs text-stone-400">{publishedLabel}</p>
              </div>

              {intro && <p className="text-stone-600 text-base leading-relaxed mb-6">{intro}</p>}

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
