"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { Search, Sparkles, SlidersHorizontal } from "lucide-react";
import { formatPrice, getLinksForLocale } from "@/lib/affiliate-links";
import type { SearchApiResponse, SearchResultItem, ArticleMatch } from "@/types/search";

interface FilterData {
  merchants:  { key: string; label: string }[];
  categories: { slug: string; name: string }[];
}

const EXAMPLES: Record<string, string[]> = {
  fr: [
    "Je recherche une TV 4K moins de 600€…",
    "Meilleure souris pour jouer aux FPS…",
    "PC portable gamer avec RTX 4070, budget 1200€…",
    "Clavier mécanique silencieux pour bureau…",
    "Casque Bluetooth premium moins de 300€…",
    "Smartphone Android milieu de gamme 2026…",
  ],
  en: [
    "Best 4K TV under 600€…",
    "Gaming mouse for FPS, under 80€…",
    "Lightweight laptop for university…",
    "Mechanical keyboard, quiet switches…",
    "Premium wireless headphones under 300€…",
  ],
};

const UI = {
  fr: {
    placeholder: "Décrivez ce que vous recherchez…",
    thinking: "Analyse en cours…",
    noResults: "Aucun résultat. Essayez d'autres mots-clés.",
    products: "Produits",
    selections: "Nos sélections",
    allNiches: "Toutes les niches",
    allMerchants: "Tous les marchands",
    niche: "Niche",
    merchant: "Marchand",
  },
  en: {
    placeholder: "Describe what you're looking for…",
    thinking: "Analyzing…",
    noResults: "No results. Try different keywords.",
    products: "Products",
    selections: "Our picks",
    allNiches: "All niches",
    allMerchants: "All merchants",
    niche: "Niche",
    merchant: "Merchant",
  },
};

// ── Compact product row ────────────────────────────────────────────────────────
function ProductRow({ item, locale }: { item: SearchResultItem; locale: string }) {
  const locLinks = getLinksForLocale(item.links, locale);
  const inStock  = locLinks.filter((l) => l.in_stock);
  const bestLink = (inStock.length ? inStock : locLinks).sort(
    (a, b) => (a.price ?? Infinity) - (b.price ?? Infinity),
  )[0];

  if (!bestLink) return null;

  return (
    <a
      href={bestLink.url}
      target="_blank"
      rel="noopener noreferrer sponsored"
      className="flex items-center gap-3 px-4 py-2.5 hover:bg-stone-50 transition-colors"
    >
      <div className="w-10 h-10 shrink-0 rounded-lg overflow-hidden bg-stone-100 border border-stone-100 flex items-center justify-center text-lg">
        {item.image_url
          ? /* eslint-disable-next-line @next/next/no-img-element */
            <img src={item.image_url} alt={item.name} className="w-full h-full object-contain p-0.5"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
          : <span className="text-stone-300">📦</span>
        }
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-stone-800 leading-snug truncate">{item.name}</p>
        {item.brand && <p className="text-xs text-stone-400 truncate">{item.brand}</p>}
      </div>
      {bestLink.price != null && (
        <span className="shrink-0 text-sm font-bold text-amber-600 whitespace-nowrap">
          {formatPrice(bestLink.price, bestLink.currency, locale)}
        </span>
      )}
      <span className="text-stone-300 text-sm shrink-0">→</span>
    </a>
  );
}

// ── Compact article row ────────────────────────────────────────────────────────
function ArticleRow({ article, locale }: { article: ArticleMatch; locale: string }) {
  // Prefer absolute https:// URLs; fall back to relative "/" paths only if no http URL available
  const thumb = article.pinImages.find((u) => u.startsWith("http"))
             ?? article.pinImages.find((u) => u.startsWith("/"));
  return (
    <Link
      href={`/${locale}/top/${article.slug}`}
      className="flex items-center gap-3 px-4 py-2.5 hover:bg-amber-50 transition-colors"
    >
      <div className="w-10 h-10 shrink-0 rounded-lg overflow-hidden bg-amber-100 flex items-center justify-center">
        {thumb
          ? /* eslint-disable-next-line @next/next/no-img-element */
            <img src={thumb} alt={article.title} className="w-full h-full object-cover" />
          : <span className="text-amber-400 text-lg">✦</span>
        }
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-stone-800 leading-snug line-clamp-2">{article.title}</p>
        {article.subcategory && (
          <span className="text-[10px] font-bold text-amber-600 uppercase tracking-wide">{article.subcategory}</span>
        )}
      </div>
      <span className="text-stone-300 text-sm shrink-0">→</span>
    </Link>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────
interface Props {
  locale: string;
  /** When set, scopes the search to this niche (niche slug). The niche select is hidden. */
  defaultNiche?: string;
}

export function AiSearch({ locale, defaultNiche }: Props) {
  const ui       = UI[locale as keyof typeof UI] ?? UI.fr;
  const examples = EXAMPLES[locale as keyof typeof EXAMPLES] ?? EXAMPLES.fr;

  const [query,    setQuery]    = useState("");
  const [loading,  setLoading]  = useState(false);
  const [response, setResponse] = useState<SearchApiResponse | null>(null);
  const [error,    setError]    = useState<string | null>(null);
  const [placeholderIdx,     setPlaceholderIdx]     = useState(0);
  const [placeholderVisible, setPlaceholderVisible] = useState(true);

  // Filters — nicheFilter is locked to defaultNiche when on a niche page
  const [nicheFilter,    setNicheFilter]    = useState<string>(defaultNiche ?? "all");
  const [merchantFilter, setMerchantFilter] = useState<string>("all");
  const [filterOpen,     setFilterOpen]     = useState(false);
  const [filterData,     setFilterData]     = useState<FilterData | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef     = useRef<HTMLTextAreaElement>(null);
  const abortRef     = useRef<AbortController | null>(null);
  const debounceRef  = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load filter options once
  useEffect(() => {
    fetch("/api/filters").then((r) => r.json()).then(setFilterData).catch(() => {});
  }, []);

  // Cycle placeholder examples
  useEffect(() => {
    const interval = setInterval(() => {
      setPlaceholderVisible(false);
      setTimeout(() => {
        setPlaceholderIdx((i) => (i + 1) % examples.length);
        setPlaceholderVisible(true);
      }, 300);
    }, 3500);
    return () => clearInterval(interval);
  }, [examples.length]);

  // Close dropdown + filter on click outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setResponse(null);
        setError(null);
        setFilterOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Core fetch — re-created when locale or filters change (triggers re-search via auto-search effect)
  const performSearch = useCallback(async (q: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setResponse(null);
    setError(null);
    try {
      const res  = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, locale, nicheFilter, merchantFilter }),
        signal: controller.signal,
      });
      const data = await res.json() as SearchApiResponse;
      if (!res.ok) {
        setError((data as { error?: string }).error ?? `Erreur ${res.status}`);
      } else {
        setResponse(data);
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError("Impossible de joindre le serveur.");
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [locale, nicheFilter, merchantFilter]);

  // Auto-search on keystroke (debounced) — also fires when filters change (performSearch identity changes)
  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setResponse(null);
      setError(null);
      return;
    }
    debounceRef.current = setTimeout(() => performSearch(trimmed), 400);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, performSearch]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); performSearch(query.trim()); }
    if (e.key === "Escape") { setResponse(null); setError(null); setFilterOpen(false); }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setQuery(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  const hasActiveFilter = (nicheFilter !== "all" && nicheFilter !== (defaultNiche ?? "all")) || merchantFilter !== "all";
  const products   = response?.results  ?? [];
  const articles   = response?.articles ?? [];
  const hasResults = products.length > 0 || articles.length > 0;
  const showDropdown = (hasResults || !!error) && !loading;

  return (
    <div ref={containerRef} className="relative z-10 w-full max-w-2xl mx-auto">
      {/* ── Search box ── */}
      <div className="flex items-end gap-2 bg-white/70 backdrop-blur-md border border-amber-200/60 shadow-lg rounded-2xl px-4 py-3 focus-within:border-amber-400 focus-within:ring-2 focus-within:ring-amber-100 transition-all">
        {loading
          ? <Sparkles className="w-5 h-5 text-amber-500 animate-pulse shrink-0 mb-0.5" />
          : <Search   className="w-5 h-5 text-stone-400 shrink-0 mb-0.5" />
        }
        <textarea
          ref={inputRef}
          rows={1}
          value={query}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={placeholderVisible ? examples[placeholderIdx] : ""}
          className="flex-1 bg-transparent outline-none text-stone-900 placeholder-stone-400 text-base resize-none overflow-hidden leading-6"
          style={{ minHeight: "1.5rem", maxHeight: "8rem" }}
          aria-label={ui.placeholder}
        />

        {/* Filter button — remplace le bouton envoi */}
        <div className="relative shrink-0 mb-0.5">
          <button
            onClick={() => setFilterOpen((prev) => !prev)}
            className={`p-2 rounded-xl border transition-colors flex items-center gap-1 ${
              hasActiveFilter
                ? "border-amber-400 bg-amber-100 text-amber-700"
                : "border-amber-200 bg-amber-50 text-amber-600 hover:bg-amber-100"
            }`}
            aria-label="Filtres"
          >
            <SlidersHorizontal className="w-4 h-4" />
            {hasActiveFilter && <span className="w-1.5 h-1.5 rounded-full bg-amber-500 shrink-0" />}
          </button>

          {/* Filter dropdown panel */}
          {filterOpen && (
            <div className="absolute right-0 top-full mt-2 bg-white rounded-xl shadow-xl border border-stone-100 p-3 z-[80] min-w-[210px] flex flex-col gap-3">
              {/* Niche select — hidden when search is scoped to a specific niche page */}
              {!defaultNiche && (
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] font-bold text-stone-400 uppercase tracking-widest">{ui.niche}</label>
                  <select
                    value={nicheFilter}
                    onChange={(e) => setNicheFilter(e.target.value)}
                    className="text-sm border border-stone-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-amber-300 cursor-pointer"
                  >
                    <option value="all">{ui.allNiches}</option>
                    {filterData?.categories.map((c) => (
                      <option key={c.slug} value={c.slug}>{c.name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div className="flex flex-col gap-1">
                <label className="text-[10px] font-bold text-stone-400 uppercase tracking-widest">{ui.merchant}</label>
                <select
                  value={merchantFilter}
                  onChange={(e) => setMerchantFilter(e.target.value)}
                  className="text-sm border border-stone-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-amber-300 cursor-pointer"
                >
                  <option value="all">{ui.allMerchants}</option>
                  {filterData?.merchants.map((m) => (
                    <option key={m.key} value={m.key}>{m.label}</option>
                  ))}
                </select>
              </div>
              {hasActiveFilter && (
                <button
                  onClick={() => { setNicheFilter(defaultNiche ?? "all"); setMerchantFilter("all"); }}
                  className="text-xs text-stone-400 hover:text-stone-600 text-center pt-1 border-t border-stone-100 transition-colors"
                >
                  Réinitialiser les filtres
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Loading indicator ── */}
      {loading && (
        <div className="absolute top-full left-0 right-0 mt-2 bg-white/90 backdrop-blur-md rounded-2xl border border-stone-100 shadow-xl px-5 py-4 z-[70]">
          <div className="flex items-center gap-2 text-sm text-stone-500">
            <Sparkles className="w-4 h-4 text-amber-500 animate-pulse" />
            {ui.thinking}
          </div>
        </div>
      )}

      {/* ── Results dropdown ── */}
      {showDropdown && (
        <div className="absolute top-full left-0 right-0 mt-2 bg-white rounded-2xl border border-stone-100 shadow-2xl z-[70] overflow-hidden max-h-[70vh] overflow-y-auto">

          {error && (
            <div className="px-4 py-3 text-sm text-red-600 bg-red-50">{error}</div>
          )}

          {!error && !hasResults && (
            <div className="px-4 py-5 text-sm text-stone-400 text-center">{ui.noResults}</div>
          )}

          {products.length > 0 && (
            <div>
              <div className="px-4 py-2 text-[11px] font-bold text-stone-400 uppercase tracking-widest border-b border-stone-100 bg-stone-50 sticky top-0">
                {ui.products} <span className="text-stone-300">({products.length})</span>
              </div>
              {products.map((item) => (
                <ProductRow key={item.id} item={item} locale={locale} />
              ))}
            </div>
          )}

          {products.length > 0 && articles.length > 0 && (
            <div className="h-px bg-stone-100" />
          )}

          {articles.length > 0 && (
            <div>
              <div className="px-4 py-2 text-[11px] font-bold text-amber-600 uppercase tracking-widest border-b border-amber-100 bg-amber-50/60 sticky top-0">
                {ui.selections} <span className="text-amber-300">({articles.length})</span>
              </div>
              {articles.map((article) => (
                <ArticleRow key={article.slug} article={article} locale={locale} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
