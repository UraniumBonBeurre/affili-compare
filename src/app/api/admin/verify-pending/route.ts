import { NextRequest, NextResponse } from "next/server";
import { readFileSync, writeFileSync, existsSync } from "fs";
import { join } from "path";
import { createServiceClient } from "@/lib/supabase";

const PENDING_PATH = join(process.cwd(), "config", "verify_pending.json");

function readPending(): object[] {
  if (!existsSync(PENDING_PATH)) return [];
  try {
    return JSON.parse(readFileSync(PENDING_PATH, "utf-8"));
  } catch {
    return [];
  }
}

export async function GET() {
  return NextResponse.json(readPending());
}

export async function POST(req: NextRequest) {
  const { productId, category, niche, productType } = await req.json();

  const supabase = createServiceClient();
  const { error } = await supabase
    .from("products")
    .update({ llm_category: category, llm_niche: niche, llm_product_type: productType })
    .eq("id", productId);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const items = readPending() as Array<{ product: { id: string } }>;
  const updated = items.filter(item => item.product.id !== productId);
  writeFileSync(PENDING_PATH, JSON.stringify(updated, null, 2), "utf-8");

  return NextResponse.json({ ok: true });
}

export async function DELETE() {
  writeFileSync(PENDING_PATH, "[]", "utf-8");
  return NextResponse.json({ ok: true });
}
