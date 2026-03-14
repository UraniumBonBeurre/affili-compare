import { NextRequest, NextResponse } from "next/server";
import { createSupabaseServerClient, createServiceClient } from "@/lib/supabase";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const category = searchParams.get("category");
  const niche    = searchParams.get("niche");
  const type     = searchParams.get("type");

  const supabase = createSupabaseServerClient();
  let q = supabase
    .from("products")
    .select("id, name, brand, description, price, affiliate_url")
    .not("active", "is", false)
    .order("name")
    .limit(200);

  if (category) q = q.eq("llm_category", category);
  if (niche)    q = q.eq("llm_niche",    niche);
  if (type)     q = q.eq("llm_product_type", type);

  const { data, error } = await q;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}

export async function PATCH(req: NextRequest) {
  const { id, llm_category, llm_niche, llm_product_type } = await req.json();
  const supabase = createServiceClient();
  const { error } = await supabase
    .from("products")
    .update({ llm_category, llm_niche, llm_product_type })
    .eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
