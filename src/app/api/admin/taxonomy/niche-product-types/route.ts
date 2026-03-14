import { NextRequest, NextResponse } from "next/server";
import { writeFileSync } from "fs";
import { join } from "path";
import type { NicheProductTypesMap } from "@/lib/site-categories";
import { clearCache } from "@/lib/site-categories";

export async function PUT(req: NextRequest) {
  const data: NicheProductTypesMap = await req.json();
  const path = join(process.cwd(), "config", "taxonomy", "niche_product_types.json");
  writeFileSync(path, JSON.stringify(data, null, 2), "utf-8");
  clearCache();
  return NextResponse.json({ ok: true });
}
