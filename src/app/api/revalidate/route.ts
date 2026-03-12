/**
 * POST /api/revalidate
 *
 * Déclenche la revalidation ISR d'une page ou de toutes les pages.
 * Protégé par REVALIDATE_SECRET (header ou body).
 *
 * Body JSON :
 *   { "secret": "...", "path": "/fr/aspirateurs-sans-fil/meilleures-aspirateurs" }
 *   { "secret": "...", "path": "/" }   ← revalide la home
 *
 * Appelé par :
 *   - GitHub Actions (update-prices.yml, update-awin-feeds.yml)
 *   - scripts/generate-content.py
 */

import { revalidatePath } from "next/cache";
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

export async function POST(request: NextRequest): Promise<NextResponse> {
  let body: { secret?: string; path?: string } = {};

  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const secret = body.secret ?? request.headers.get("x-revalidate-secret");

  if (!process.env.REVALIDATE_SECRET || secret !== process.env.REVALIDATE_SECRET) {
    return NextResponse.json({ error: "Invalid or missing secret" }, { status: 401 });
  }

  const path = body.path ?? "/";

  try {
    revalidatePath(path, "page");
    return NextResponse.json({
      revalidated: true,
      path,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    return NextResponse.json(
      { error: "Revalidation failed", details: String(error) },
      { status: 500 }
    );
  }
}

// Reject GET / other methods
export async function GET(): Promise<NextResponse> {
  return NextResponse.json({ error: "Method not allowed" }, { status: 405 });
}
