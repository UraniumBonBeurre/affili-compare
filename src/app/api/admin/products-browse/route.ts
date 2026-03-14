import { NextRequest, NextResponse } from "next/server";
import { createSupabaseServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

export async function GET(req: NextRequest) {
  const p        = req.nextUrl.searchParams;
  const page     = Math.max(0, parseInt(p.get("page") ?? "0", 10) || 0);
  const merchant = p.get("merchant") ?? "";
  const unclassifiedOnly = p.get("unclassified") === "1";
  const noEmbeddingOnly  = p.get("no_embedding")  === "1";

  const supabase = createSupabaseServerClient();

  let query = supabase
    .from("products")
    .select("id, name, brand, merchant_key, merchant_name, price, llm_category, llm_niche, active, embedding_text")
    .not("active", "is", false)
    .order("created_at", { ascending: false })
    .range(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE - 1);

  if (merchant) query = query.eq("merchant_key", merchant);
  if (unclassifiedOnly) query = query.is("llm_category", null);
  if (noEmbeddingOnly)  query = query.is("embedding_text", null);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const products = (data ?? []).map((p) => ({
    id:           p.id,
    name:         (p.name ?? "").slice(0, 60),
    brand:        p.brand ?? "",
    merchant:     p.merchant_key ?? "",
    price:        p.price,
    llm_category: p.llm_category,
    llm_niche:    p.llm_niche,
    active:       p.active,
    has_embedding: p.embedding_text != null,
  }));

  return NextResponse.json(
    { products, page, has_more: products.length === PAGE_SIZE },
    { headers: { "Cache-Control": "no-store" } }
  );
}
