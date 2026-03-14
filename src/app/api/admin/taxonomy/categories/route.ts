import { NextRequest, NextResponse } from "next/server";
import { writeFileSync } from "fs";
import { join } from "path";
import type { SiteCategory } from "@/lib/site-categories";
import { clearCache } from "@/lib/site-categories";

export async function PUT(req: NextRequest) {
  const { categories }: { categories: SiteCategory[] } = await req.json();
  const path = join(process.cwd(), "config", "taxonomy", "categories.json");
  writeFileSync(path, JSON.stringify({ categories }, null, 2), "utf-8");
  clearCache();
  return NextResponse.json({ ok: true });
}
