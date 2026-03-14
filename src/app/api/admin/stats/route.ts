import { NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const PAGE = 2000;

export async function GET() {
  const supabase = createServiceClient();

  // ── Headline counts via head:true (no data transfer) ──────────────────────
  const [
    { count: total },
    { count: active },
    { count: classified },
    { count: hasEmbedding },
    { count: inactive },
  ] = await Promise.all([
    supabase.from("products").select("*", { count: "exact", head: true }),
    supabase.from("products").select("*", { count: "exact", head: true }).not("active", "is", false),
    supabase.from("products").select("*", { count: "exact", head: true }).not("active", "is", false).not("llm_category", "is", null),
    supabase.from("products").select("*", { count: "exact", head: true }).not("active", "is", false).not("embedding_text", "is", null),
    supabase.from("products").select("*", { count: "exact", head: true }).eq("active", false),
  ]);

  // ── Per-merchant breakdown (small columns, paginated) ──────────────────────
  type Row = { merchant_key: string | null; merchant_name: string | null; llm_category: string | null; embedding_text: string | null };
  const rows: Row[] = [];
  let from = 0;
  while (true) {
    const { data, error } = await supabase
      .from("products")
      .select("merchant_key, merchant_name, llm_category, embedding_text")
      .not("active", "is", false)
      .range(from, from + PAGE - 1);
    if (error || !data || data.length === 0) break;
    rows.push(...(data as Row[]));
    if (data.length < PAGE) break;
    from += PAGE;
  }

  // Aggregate per merchant
  const merchantMap = new Map<string, { name: string; total: number; classified: number; has_embedding: number }>();
  for (const row of rows) {
    const key = row.merchant_key ?? "(inconnu)";
    if (!merchantMap.has(key)) {
      merchantMap.set(key, { name: row.merchant_name ?? key, total: 0, classified: 0, has_embedding: 0 });
    }
    const m = merchantMap.get(key)!;
    m.total++;
    if (row.llm_category) m.classified++;
    if (row.embedding_text) m.has_embedding++;
  }

  const merchants = Array.from(merchantMap.entries())
    .map(([key, v]) => ({ key, ...v }))
    .sort((a, b) => b.total - a.total);

  const activeN = active ?? 0;
  const classifiedN = classified ?? 0;

  return NextResponse.json(
    {
      total:          total ?? 0,
      active:         activeN,
      classified:     classifiedN,
      unclassified:   activeN - classifiedN,
      has_embedding:  hasEmbedding ?? 0,
      needs_embedding: activeN - (hasEmbedding ?? 0),
      inactive:       inactive ?? 0,
      merchants,
    },
    { headers: { "Cache-Control": "no-store" } }
  );
}
