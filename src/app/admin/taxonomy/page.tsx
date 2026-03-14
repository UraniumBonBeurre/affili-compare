import { getSiteCategories, getNicheProductTypes } from "@/lib/site-categories";
import { createSupabaseServerClient } from "@/lib/supabase";
import TaxonomyDashboard from "@/components/admin/TaxonomyDashboard";

export const dynamic = "force-dynamic";

type TypeCounts = Record<string, number>;
type NicheStats = { total: number; types: TypeCounts };
type CatStats   = { total: number; niches: Record<string, NicheStats> };
type StatsMap   = Record<string, CatStats>;

async function fetchStats(): Promise<{ stats: StatsMap; total: number; classified: number }> {
  const supabase = createSupabaseServerClient();
  const PAGE = 1000;
  const map: StatsMap = {};
  let total = 0;
  let classified = 0;
  let from = 0;

  while (true) {
    const { data, error } = await supabase
      .from("products")
      .select("llm_category, llm_niche, llm_product_type")
      .not("active", "is", false)
      .range(from, from + PAGE - 1);

    if (error || !data || data.length === 0) break;

    for (const p of data) {
      const cat  = (p.llm_category  as string | null) || "__none__";
      const nich = (p.llm_niche     as string | null) || "__none__";
      const type = (p.llm_product_type as string | null) || "autre";
      if (!map[cat])               map[cat] = { total: 0, niches: {} };
      if (!map[cat].niches[nich])  map[cat].niches[nich] = { total: 0, types: {} };
      map[cat].total++;
      map[cat].niches[nich].total++;
      map[cat].niches[nich].types[type] = (map[cat].niches[nich].types[type] ?? 0) + 1;
      total++;
      if (p.llm_category) classified++;
    }

    if (data.length < PAGE) break;
    from += PAGE;
  }

  return { stats: map, total, classified };
}

export default async function TaxonomyPage() {
  const categories = getSiteCategories();
  const nicheProductTypes = getNicheProductTypes();
  const { stats, total, classified } = await fetchStats();

  return (
    <TaxonomyDashboard
      categories={categories}
      nicheProductTypes={nicheProductTypes}
      stats={stats}
      total={total}
      classified={classified}
    />
  );
}
