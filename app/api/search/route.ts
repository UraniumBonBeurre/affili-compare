/**
 * POST /api/search
 * Body: { query: string, locale?: "fr" | "en" | "de" }
 *
 * Pipeline :
 *   1. Analyse sémantique (lib/search-utils) : synonymes + intention prix + marque + prix
 *   2. Embedding de la requête (lib/embedding.ts) → vecteur 384 dims
 *   3a. Recherche HYBRIDE (pgvector 60% + trigram 25% + BM25 15%) via Supabase RPC
 *   3b. Fallback SQL classique (OR ILIKE) si pas d'embedding disponible
 *   4. Enrichissement (affiliate_links, comparisons, categories)
 *   5. Tri déterministe par intention prix (priceIntent)
 */

import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { parseQuery } from "@/lib/search-utils";
import { embedQuery } from "@/lib/embedding";
import type { SearchResultItem, SearchApiResponse, SearchAffiliateLink } from "@/types/search";

/**
 * Détecte la catégorie la plus probable à partir de la requête brute.
 * Retourne null si ambigu ou inconnu → pas de filtre catégorie.
 */
function detectQueryCategory(query: string): string | null {
  const q = query.toLowerCase();
  const isTV = /\btv\b|\bt[eé]l[eé]\b|t[eé]l[eé]vision|oled|qled|vid[eé]oprojecteur|barre de son|enceinte bluetooth/.test(q);
  // Exclure les requêtes mobilier : "chaise gaming", "fauteuil gaming" ne sont pas des
  // périphériques gaming → ne pas forcer la catégorie gaming sur ces requêtes.
  const isGaming = /\bgaming\b|\bgamer\b|\bmanette\b|fauteuil gamer|volant gaming/.test(q)
    && !/\bchaise\b|\bfauteuil\b|\bsi[eè]ge\b/.test(q);
  const isSmartphone = /\bsmartphone\b|\bt[eé]l[eé]phone\b|\bandroid\b|\biphone\b/.test(q);
  const isElectromenager = /\baspirateur\b|\bfrigo\b|r[eé]frig[eé]rateur|lave-linge|s[eè]che-linge|machine.+caf[eé]|\bbouilloire\b|\bmixeur\b|\bclimatiseur\b/.test(q);
  const isInformatique = /\bpc\b|\bordinateur\b|\blaptop\b|\bssd\b|disque dur|carte graphique|\bprocesseur\b/.test(q);

  const count = [isTV, isGaming, isSmartphone, isElectromenager, isInformatique].filter(Boolean).length;
  if (count !== 1) return null; // ambiguïté ou aucun signal → pas de filtre
  if (isTV) return "tv-hifi";
  if (isGaming) return "gaming";
  if (isSmartphone) return "smartphone";
  if (isElectromenager) return "electromenager";
  if (isInformatique) return "informatique";
  return null;
}

export async function POST(req: Request) {
  let query = "";
  let locale: "fr" | "en" | "de" = "fr";
  try {
    const body = await req.json();
    query = String(body.query ?? "").trim().slice(0, 500);
    locale = ["fr", "en", "de"].includes(body.locale) ? body.locale : "fr";
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  if (!query) {
    return NextResponse.json({ results: [], fromLLM: false } satisfies SearchApiResponse);
  }

  const { sqlKeywords, priceIntent, rawQuery, brand, maxPrice, minPrice } = parseQuery(query);
  // Try both original and NFD-normalized (no accents) for category detection
  const normQuery = query.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const categoryFilter = detectQueryCategory(rawQuery) ?? detectQueryCategory(normQuery);

  const noResultMsg =
    locale === "en" ? "No results. Try different keywords."
    : locale === "de" ? "Keine Ergebnisse. Versuchen Sie andere Suchbegriffe."
    : "Aucun résultat. Essayez d'autres mots-clés.";

  if (!sqlKeywords.length) {
    return NextResponse.json({ results: [], fromLLM: false, message: noResultMsg } satisfies SearchApiResponse);
  }

  // ── 1. Embedding de la requête (tente vectorielle, graceful fallback) ────────
  // Fallback : essayer la version sans accents si le modèle Xenova échoue sur unicode
  const queryEmbedding =
    await embedQuery(rawQuery) ??
    await embedQuery(normQuery);

  // ── 2. Recherche des produits ─────────────────────────────────────────────────
  let allProducts: { id: string; name: string; brand: string | null; image_url: string | null; rating: number | null; review_count: number | null; category_slug: string | null; affiliate_url?: string | null; price?: number | null; currency?: string | null; in_stock?: boolean | null; merchant_key?: string | null; }[] = [];

  if (queryEmbedding !== null) {
    // ── 2a. Recherche hybride vectorielle + BM25 ─────────────────────────────
    const { data: vectorResults, error: vectorError } = await supabase.rpc(
      "search_products_hybrid",
      {
        query_embedding:  queryEmbedding,
        // Utiliser les sqlKeywords normalisés pour le BM25 (pas rawQuery avec accents)
        // → permet à tous les produits avec "tv hifi" de matcher pour "télévision 4K"
        query_text:       sqlKeywords.join(" "),
        match_count:      20,
        brand_filter:     brand ?? null,
        category_filter:  categoryFilter,
      }
    );

    if (!vectorError && vectorResults?.length) {
      // Garde de pertinence : si aucun résultat n'a de correspondance FTS (branche lexicale)
      // ET qu'on n'a ni filtre catégorie ni filtre marque → la requête est hors-catalogue.
      // Ex: "fleur", "voiture", "recette gateau" → retourner vide plutôt que les voisins vectoriels.
      const anyLexicalMatch = vectorResults.some((r: { in_lexical?: boolean }) => r.in_lexical);
      // Garde de pertinence : aucun résultat lexical → requête hors-catalogue.
      // S'applique aussi quand un categoryFilter est présent (ex: "chaise gaming" en catégorie
      // gaming → FTS ne trouve aucun meuble → retourner vide plutôt que des périphériques).
      if (!anyLexicalMatch && !brand) {
        return NextResponse.json({ results: [], fromLLM: false, message: noResultMsg } satisfies SearchApiResponse);
      }

      allProducts = vectorResults.map((r: { id: string; name: string; brand: string | null; image_url: string | null; rating: number | null; review_count: number | null; category_slug: string | null; affiliate_url?: string | null; price?: number | null; currency?: string | null; in_stock?: boolean | null; merchant_key?: string | null }) => ({
        id: r.id, name: r.name, brand: r.brand, image_url: r.image_url,
        rating: r.rating, review_count: r.review_count ?? 0, category_slug: r.category_slug ?? null,
        affiliate_url: r.affiliate_url ?? null, price: r.price ?? null,
        currency: r.currency ?? null, in_stock: r.in_stock ?? null, merchant_key: r.merchant_key ?? null,
      }));
    } else if (vectorError) {
      // pgvector non activé ou colonnes manquantes → fallback SQL classique
      console.warn("[search] Vector search failed, falling back to SQL:", vectorError.message);
    }
  }

  // ── 2b. Fallback SQL classique si vectorielle a échoué ou pas d'embedding ────
  if (!allProducts.length) {
    const productOrFilter = sqlKeywords.map((k) => `name.ilike.%${k}%,brand.ilike.%${k}%`).join(",");
    const sqlBase = supabase
      .from("products")
      .select("id, name, brand, image_url, rating, review_count, category_slug, affiliate_url, price, currency, in_stock, merchant_key")
      .or(productOrFilter)
      .limit(40);
    const { data: sqlProducts } = categoryFilter
      ? await sqlBase.eq("category_slug", categoryFilter)
      : await sqlBase;

    // Recherche via titres de comparatifs si toujours vide
    if ((sqlProducts?.length ?? 0) === 0) {
      const titleKey = locale === "en" ? "title_en" : locale === "de" ? "title_de" : "title_fr";
      const compOrFilter = sqlKeywords.map((k) => `${titleKey}.ilike.%${k}%`).join(",");
      const { data: matchedComps } = await supabase
        .from("comparisons")
        .select("id, slug, title_fr, title_en, title_de, category_id")
        .or(compOrFilter)
        .eq("is_published", true)
        .limit(10);

      if (matchedComps?.length) {
        const compIds = matchedComps.map((c) => c.id);
        const { data: cpRows } = await supabase
          .from("comparison_products")
          .select("product_id")
          .in("comparison_id", compIds)
          .limit(40);
        const extraIds = (cpRows ?? []).map((r) => r.product_id);
        if (extraIds.length) {
          const { data: extraProds } = await supabase
            .from("products")
            .select("id, name, brand, image_url, rating, review_count, affiliate_url, price, currency, in_stock, merchant_key")
            .in("id", extraIds);
          allProducts = (extraProds ?? []).map((p) => ({ ...p, review_count: p.review_count ?? 0, category_slug: null }));
        }
      }
    } else {
      allProducts = (sqlProducts ?? []).map((p) => ({ ...p, review_count: p.review_count ?? 0, category_slug: (p as { category_slug?: string | null }).category_slug ?? null }));
    }
  }

  // ── 2c. Supplément : si category_filter actif mais pas de produit principal trouvé
  // (ex: "télévision 4K" → vector renvoie des supports TV, pas des Samsung/LG)
  if (categoryFilter && brand === null && allProducts.length > 0) {
    const MAIN_PRODUCT_BRANDS: Record<string, string[]> = {
      "tv-hifi":     ["Samsung","LG","TCL","Philips","Sony","Hisense","Panasonic","Sharp"],
      "gaming":      ["Logitech","Razer","Corsair","SteelSeries","Asus","MSI"],
      "smartphone":  ["Samsung","Apple","Xiaomi","OnePlus","Google","Motorola","Oppo"],
      "informatique":["HP","Dell","Lenovo","Asus","Acer","Apple","MSI"],
    };
    const keyBrands = MAIN_PRODUCT_BRANDS[categoryFilter] ?? [];
    // Déclencher le supplément si aucune marque principale dans les 5 premiers.
    // (Condition plus stricte que "absente des résultats" : couvre le cas où
    //  Lenovo est en position 10 derrière 9 docking-stations StarTech.)
    const hasMainBrandInTop5 = keyBrands.length === 0 || allProducts.slice(0, 5).some(
      (p) => keyBrands.some((b) => (p.brand ?? "").toLowerCase().includes(b.toLowerCase()))
    );
    if (!hasMainBrandInTop5 && keyBrands.length > 0) {
      const { data: topRated } = await supabase
        .from("products")
        .select("id, name, brand, image_url, rating, review_count, category_slug")
        .eq("category_slug", categoryFilter)
        .in("brand", keyBrands)
        .limit(10);
      const existingIds = new Set(allProducts.map((p) => p.id));
      const extra = (topRated ?? [])
        .filter((p) => !existingIds.has(p.id))
        .map((p) => ({ ...p, review_count: (p as { review_count?: number | null }).review_count ?? 0, category_slug: (p as { category_slug?: string | null }).category_slug ?? null }));
      allProducts = [...extra, ...allProducts];
    }
  }

  if (!allProducts.length) {
    return NextResponse.json({ results: [], fromLLM: false, message: noResultMsg } satisfies SearchApiResponse);
  }

  // ── 3. Liens affiliates ───────────────────────────────────────────────────────
  const allIds = allProducts.map((p) => p.id);

  const { data: links } = await supabase
    .from("affiliate_links")
    .select("id, product_id, partner, price, currency, url, in_stock")
    .in("product_id", allIds);

  // ── 4. Contexte comparatifs / catégories (pour produits sans category_slug) ──
  const missingCatIds = allProducts.filter((p) => !p.category_slug).map((p) => p.id);
  let dynamicCatMap: Record<string, { comparison_slug: string | null; category_slug: string | null }> = {};

  if (missingCatIds.length) {
    const { data: compProds } = await supabase
      .from("comparison_products")
      .select("product_id, comparison_id")
      .in("product_id", missingCatIds)
      .limit(80);

    const compProdCompIds = [...new Set((compProds ?? []).map((cp) => cp.comparison_id))];
    const { data: allComps } = compProdCompIds.length
      ? await supabase.from("comparisons").select("id, slug, category_id").in("id", compProdCompIds).eq("is_published", true)
      : { data: [] };

    const catIds = [...new Set((allComps ?? []).map((c) => c.category_id))];
    const { data: cats } = catIds.length
      ? await supabase.from("categories").select("id, slug").in("id", catIds)
      : { data: [] };

    for (const cp of compProds ?? []) {
      const comp = (allComps ?? []).find((c) => c.id === cp.comparison_id);
      const cat  = comp ? (cats ?? []).find((c) => c.id === comp.category_id) : null;
      if (!dynamicCatMap[cp.product_id]) {
        dynamicCatMap[cp.product_id] = {
          comparison_slug: comp?.slug ?? null,
          category_slug:   cat?.slug  ?? null,
        };
      }
    }
  }

  // ── 5. Construction des objets résultat ──────────────────────────────────────
  const results: SearchResultItem[] = allProducts
    .map((p) => {
      let productLinks: SearchAffiliateLink[] = (links ?? [])
        .filter((l) => l.product_id === p.id)
        .map((l) => ({ id: l.id, partner: l.partner, price: l.price, currency: l.currency, url: l.url, in_stock: l.in_stock }));

      // Fallback pour les produits importés en bulk (pas d'affiliate_links, mais affiliate_url sur le produit)
      if (!productLinks.length && p.affiliate_url && p.price != null) {
        productLinks = [{ id: p.id, partner: p.merchant_key ?? "merchant", price: p.price, currency: p.currency ?? "EUR", url: p.affiliate_url, in_stock: p.in_stock ?? true }];
      }

      const ctx = dynamicCatMap[p.id] ?? {};
      const comparison_slug = ctx.comparison_slug ?? null;
      const category_slug   = p.category_slug ?? ctx.category_slug ?? null;

      return {
        id: p.id, name: p.name, brand: p.brand, image_url: p.image_url,
        rating: p.rating, review_count: p.review_count ?? 0,
        links: productLinks,
        comparison_slug,
        category_slug,
      };
    })
    .filter((p) => {
      if (!p.links.length) return false;
      // Filtre prix si spécifié dans la requête
      const prices = p.links.filter((l) => l.price != null).map((l) => l.price!);
      if (!prices.length) return true;
      const minP = Math.min(...prices);
      if (maxPrice !== null && minP > maxPrice) return false;
      if (minPrice !== null && Math.max(...prices) < minPrice) return false;
      return true;
    });

  if (!results.length) {
    // Si le filtre prix a tout supprimé, chercher sans filtre prix pour un message utile
    if (maxPrice !== null || minPrice !== null) {
      const cheapestWithLinks = allProducts
        .filter((p) => (links ?? []).some((l) => l.product_id === p.id))
        .map((p) => {
          const pLinks = (links ?? []).filter((l) => l.product_id === p.id);
          const prices = pLinks.filter((l) => l.price != null).map((l) => l.price!);
          return { name: p.name, minPrice: prices.length ? Math.min(...prices) : null };
        })
        .filter((p) => p.minPrice !== null)
        .sort((a, b) => a.minPrice! - b.minPrice!)
        .slice(0, 1);
      const hint = cheapestWithLinks[0]
        ? ` Le moins cher disponible est à ${cheapestWithLinks[0].minPrice}€ (${cheapestWithLinks[0].name}).`
        : "";
      return NextResponse.json({ results: [], fromLLM: false, message: noResultMsg + hint } satisfies SearchApiResponse);
    }
    return NextResponse.json({ results: [], fromLLM: false, message: noResultMsg } satisfies SearchApiResponse);
  }

  // -- 6. Tri deterministe par intention prix
  // Les resultats sont deja ordonnes par hybrid_score (60% cosinus + 25% trigram + 15% BM25).
  // On reordonne uniquement si l'utilisateur exprime une contrainte de prix explicite.
  const getMinPrice = (p: SearchResultItem): number =>
    Math.min(...p.links.filter((l) => l.price != null).map((l) => l.price!), Infinity);

  const sorted =
    priceIntent === "cheapest"
      ? [...results].sort((a, b) => getMinPrice(a) - getMinPrice(b))
      : priceIntent === "premium"
      ? [...results].sort((a, b) => getMinPrice(b) - getMinPrice(a))
      : results; // deja trie par hybrid_score pgvector

  return NextResponse.json({
    results: sorted.slice(0, 10),
    fromLLM: false,
    ...(priceIntent === "cheapest" && { autoSort: "price_asc" as const }),
    ...(priceIntent === "premium"  && { autoSort: "price_desc" as const }),
  } satisfies SearchApiResponse);
}
