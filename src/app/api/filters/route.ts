import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { readFileSync } from "fs";
import { join } from "path";

export async function GET() {
  // ── Marchands actifs depuis config/merchants.json ────────────────────────
  let merchants: { key: string; label: string }[] = [];
  try {
    const raw = JSON.parse(
      readFileSync(join(process.cwd(), "config", "merchants.json"), "utf-8"),
    ) as { merchants: { key: string; label: string; active: boolean }[] };
    merchants = raw.merchants.filter((m) => m.active).map((m) => ({ key: m.key, label: m.label }));
  } catch { /* config absent → liste vide */ }

  // ── Catégories depuis Supabase ───────────────────────────────────────────
  const { data: cats } = await supabase.from("categories").select("id, slug").order("slug");
  const categories = (cats ?? []).map((c) => ({
    slug: c.slug as string,
    name: slugToLabel(c.slug as string),
  }));

  return NextResponse.json({ merchants, categories });
}

function slugToLabel(slug: string): string {
  return slug
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ")
    .replace("Tv", "TV")
    .replace("Hi Fi", "Hi-Fi");
}
