/**
 * GET /api/top5?locale=fr&limit=6&category=gaming
 *
 * Retourne les articles Top 5 publiés du mois en cours,
 * triés par date de génération décroissante.
 */

import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const limit    = Math.min(parseInt(searchParams.get("limit") ?? "6", 10), 20);
  const category = searchParams.get("category") ?? null;
  const month    = searchParams.get("month") ?? new Date().toISOString().slice(0, 7); // "2026-03"

  let query = supabase
    .from("top5_articles")
    .select("id, slug, category_slug, subcategory, title_fr, intro_fr, products, month, generated_at")
    .eq("is_published", true)
    .eq("month", month)
    .order("generated_at", { ascending: false })
    .limit(limit);

  if (category) query = query.eq("category_slug", category);

  const { data, error } = await query;

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ articles: data ?? [], month });
}
