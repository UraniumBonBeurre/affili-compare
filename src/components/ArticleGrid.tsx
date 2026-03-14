"use client";

import { useMemo } from "react";
import { GalleryCard } from "./GalleryCard";
import type { TopArticle, Locale } from "@/types/database";

interface ArticleContent {
  title_en?: string;
  subcategory?: string;
  subcategory_en?: string;
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

interface Props {
  articles: TopArticle[];
  locale: Locale;
  onOpen: (slug: string) => void;
}

export function ArticleGrid({ articles, locale, onOpen }: Props) {
  const isEn = locale === "en";

  const cards = useMemo(() =>
    articles.map((a) => {
      const c    = parseContent(a.content);
      const title = isEn ? ((c.title_en as string) || a.title) : a.title;
      const subcategory = isEn
        ? ((c.subcategory_en as string) || (c.subcategory as string) || "")
        : ((c.subcategory as string) ?? "");
      return { ...a, title, subcategory, pinImages: parsePinImages(a.pin_images) };
    }),
  [articles, isEn]);

  if (cards.length === 0) return null;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-4">
      {cards.map((card) => (
        <div key={card.slug} className="w-full">
          <GalleryCard
            slug={card.slug}
            title={card.title}
            subcategory={card.subcategory}
            pinImages={card.pinImages}
            locale={locale}
            onOpen={onOpen}
            aspectClass="aspect-square"
          />
        </div>
      ))}
    </div>
  );
}
