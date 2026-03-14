/**
 * site-categories.ts — Load and query site categories + niche product types.
 * Server-side only (uses fs.readFileSync — do not import in client components).
 */

import { readFileSync } from "fs";
import { join } from "path";

export interface SiteNiche {
  name: string;
  name_en: string;
  slug: string;
}

export interface SiteCategory {
  id: string;
  name: string;
  name_en: string;
  icon: string;
  gradient_from: string;
  gradient_to: string;
  niches: SiteNiche[];
}

export interface ProductTypeItem {
  id: string;
  name_fr: string;
  name_en: string;
}

/** Map of niche_slug → ordered list of product types */
export type NicheProductTypesMap = Record<string, ProductTypeItem[]>;

let _catCache: SiteCategory[] | null = null;
let _nptCache: NicheProductTypesMap | null = null;

export function getSiteCategories(): SiteCategory[] {
  if (_catCache) return _catCache;
  const raw = readFileSync(join(process.cwd(), "config", "taxonomy", "categories.json"), "utf-8");
  _catCache = (JSON.parse(raw) as { categories: SiteCategory[] }).categories;
  return _catCache;
}

export function getSiteCategory(id: string): SiteCategory | null {
  return getSiteCategories().find((c) => c.id === id) ?? null;
}

export function getSiteNiche(categoryId: string, nicheSlug: string): SiteNiche | null {
  return getSiteCategory(categoryId)?.niches.find((n) => n.slug === nicheSlug) ?? null;
}

export function getNicheProductTypes(): NicheProductTypesMap {
  if (_nptCache) return _nptCache;
  const raw = readFileSync(
    join(process.cwd(), "config", "taxonomy", "niche_product_types.json"),
    "utf-8"
  );
  _nptCache = JSON.parse(raw) as NicheProductTypesMap;
  return _nptCache;
}

export function clearCache() {
  _catCache = null;
  _nptCache = null;
}
