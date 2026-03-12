import type { Metadata } from "next";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { GalleryCard } from "@/components/GalleryCard";
import { AiSearch } from "@/components/AiSearch";
import type { Locale } from "@/types/database";

interface Props {
  params: { locale: Locale };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return {
    title: "MyGoodPick — Sélections produits du moment",
    description:
      params.locale === "en"
        ? "Curated product picks with real prices and affiliate links."
        : "Sélections produits indépendantes avec prix en temps réel et liens affiliés.",
  };
}

export const revalidate = 0;

async function getRecentArticles() {
  const month = new Date().toISOString().slice(0, 7);
  const { data } = await supabase
    .from("top_articles")
    .select("id, slug, title, content, pin_images, created_at")
    .gte("created_at", `${month}-01`)
    .order("created_at", { ascending: false })
    .limit(12);
  return data ?? [];
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

export default async function HomePage({ params }: Props) {
  const { locale } = params;
  const articles = await getRecentArticles();
  const isEn = locale === "en";

  const cards = articles.map((a) => {
    const c = parseContent(a.content);
    const title = isEn ? ((c.title_en as string) || a.title) : a.title;
    const subcategory = isEn
      ? ((c.subcategory_en as string) || (c.subcategory as string))
      : (c.subcategory as string) ?? "";
    const pinImages = parsePinImages(a.pin_images);
    return { slug: a.slug, title, subcategory, pinImages };
  });

  return (
    /* Full-viewport column: search bar fixed at top, cards scroll below */
    <div className="flex flex-col" style={{ height: "calc(100vh - 3.5rem - 1px)" }}>

      {/* ── Search bar — does NOT scroll ── */}
      <div className="flex-none pt-6 pb-5 px-2">
        <AiSearch locale={locale} />
      </div>

      {/* ── Galerie du mois — only this area scrolls ── */}
      {cards.length > 0 && (
        <div className="flex-1 min-h-0 overflow-y-auto px-1 pb-6">
          <div className="flex items-end mb-4">
            <h2 className="text-xl font-extrabold text-stone-800">
              {isEn ? "This month's picks" : "Sélections du mois"}
            </h2>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-4">
            {cards.map((card) => (
              <GalleryCard
                key={card.slug}
                slug={card.slug}
                title={card.title}
                subcategory={card.subcategory}
                pinImages={card.pinImages}
                locale={locale}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

