import type { MetadataRoute } from "next";
import { supabase } from "@/lib/supabase";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://mygoodpick.com";
const LOCALES  = ["fr", "en", "de"] as const;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [catRes, compRes] = await Promise.all([
    supabase.from("categories").select("slug, created_at").eq("is_active", true),
    supabase.from("comparisons")
      .select("slug, category_id, last_updated")
      .eq("is_published", true),
  ]);

  const { data: categories } = catRes;
  const { data: comparisons  } = compRes;

  const categorySlugs = (categories ?? []).map((c) => c.slug);

  const entries: MetadataRoute.Sitemap = [];

  // Homepages
  for (const locale of LOCALES) {
    entries.push({
      url:              `${SITE_URL}/${locale}`,
      lastModified:     new Date(),
      changeFrequency:  "daily",
      priority:         1.0,
    });
  }

  // Pages catégories
  for (const locale of LOCALES) {
    for (const slug of categorySlugs) {
      entries.push({
        url:             `${SITE_URL}/${locale}/${slug}`,
        changeFrequency: "weekly",
        priority:        0.8,
      });
    }
  }

  // Pages comparatifs
  for (const comp of comparisons ?? []) {
    const cat = categories?.find((c) => c.id === comp.category_id);
    if (!cat) continue;
    for (const locale of LOCALES) {
      entries.push({
        url:             `${SITE_URL}/${locale}/${cat.slug}/${comp.slug}`,
        lastModified:    new Date(comp.last_updated),
        changeFrequency: "daily",
        priority:        0.9,
      });
    }
  }

  return entries;
}
