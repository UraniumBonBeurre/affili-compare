/**
 * GET /api/top5?locale=fr&limit=6&category=gaming
 *
 * Retourne les articles Top N publiés, triés par date de génération décroissante.
 * Lit la table `top_articles` (générée par create_and_post_top_products.py).
 */

import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

interface TopArticleRow {
  id: string;
  slug: string;
  title: string;
  content: string | Record<string, unknown>;
  pin_images: string | string[] | null;
  created_at: string;
}

function parseContent(raw: string | Record<string, unknown>): Record<string, unknown> {
  if (typeof raw === "string") {
    try { return JSON.parse(raw); } catch { return {}; }
  }
  return raw ?? {};
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const limit    = Math.min(parseInt(searchParams.get("limit") ?? "6", 10), 20);
  const locale   = searchParams.get("locale") ?? "fr";
  const category = searchParams.get("category") ?? null;
  const month    = searchParams.get("month") ?? new Date().toISOString().slice(0, 7); // "2026-03"

  let query = supabase
    .from("top_articles")
    .select("id, slug, title, content, pin_images, created_at")
    .gte("created_at", `${month}-01`)
    .lte("created_at", `${month}-31`)
    .order("created_at", { ascending: false })
    .limit(limit);

  const { data, error } = await query;

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const articles = (data as TopArticleRow[] ?? []).map((row) => {
    const c = parseContent(row.content);
    // Normalise pin_images to a string array
    let pinImages: string[] = [];
    if (Array.isArray(row.pin_images)) pinImages = row.pin_images as string[];
    else if (typeof row.pin_images === "string") {
      try { pinImages = JSON.parse(row.pin_images); } catch { /* ignore */ }
    }
    return {
      id:            row.id,
      slug:          row.slug,
      category_slug: (c.category_slug as string) ?? "",
      subcategory:   (c.subcategory as string) ?? "",
      title_fr:      row.title,
      title_en:      (c.title_en as string) ?? row.title,
      intro_fr:      (c.intro_fr as string) ?? null,
      intro_en:      (c.intro_en as string) ?? null,
      products:      (c.products as unknown[]) ?? [],
      month:         (c.month as string) ?? month,
      pin_images:    pinImages,
    };
  }).filter((a) => !category || a.category_slug === category);

  return NextResponse.json({ articles, month });
}
