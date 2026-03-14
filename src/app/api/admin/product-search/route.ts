import { NextRequest, NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase";

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams.get("q")?.trim() ?? "";
  if (q.length < 2) return NextResponse.json([]);

  const supabase = createServiceClient();
  const { data, error } = await supabase
    .from("products")
    .select("id, name, brand, llm_category, llm_niche, llm_product_type")
    .ilike("name", `%${q}%`)
    .not("active", "is", false)
    .limit(20);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
