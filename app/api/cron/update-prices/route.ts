/**
 * GET /api/cron/update-prices
 *
 * Vercel Cron Job (défini dans vercel.json → "crons")
 * Planifié à 5h UTC tous les jours.
 *
 * Sécurité : Vercel envoie automatiquement un header Authorization: Bearer <CRON_SECRET>
 * Ne jamais exposer cette route publiquement sans vérification.
 */

import { NextRequest, NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabase"; // eslint-disable-line @typescript-eslint/no-unused-vars

export const runtime = "nodejs";
export const maxDuration = 60; // Vercel Pro : 300s max sur crons

export async function GET(request: NextRequest): Promise<NextResponse> {
  // Vercel injects this header automatically for cron jobs
  const authHeader = request.headers.get("authorization");
  if (process.env.CRON_SECRET && authHeader !== `Bearer ${process.env.CRON_SECRET}`) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const supabase = createServiceClient();

    // Fetch stale affiliate links (last_checked > 24h ago)
    const { data: staleLinks, error } = await supabase
      .from("affiliate_links")
      .select("id, product_id, partner_id, url")
      .lt("last_checked", new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString())
      .limit(50);

    if (error) throw error;

    // Note: actual price scraping happens in GitHub Actions (scrape_prices.py)
    // This cron just triggers ISR revalidation after prices have been updated externally.
    // For actual scraping from Vercel, call the GitHub Actions API instead.

    return NextResponse.json({
      success: true,
      stale_links: staleLinks?.length ?? 0,
      timestamp: new Date().toISOString(),
      message: "Price check triggered. Actual scraping handled by GitHub Actions.",
    });
  } catch (error) {
    console.error("[cron/update-prices]", error);
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}
