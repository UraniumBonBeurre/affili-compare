"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import Image from "next/image";
import Link from "next/link";
import { Search, SendHorizonal, Loader2, Star, ExternalLink, Sparkles, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PARTNER_COLORS,
  PARTNER_LABELS,
  formatPrice,
  getLinksForLocale,
} from "@/lib/affiliate-links";
import type { SearchApiResponse, SearchResultItem } from "@/types/search";

// ── Placeholder examples per locale ──────────────────────────────────────────
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
  de: [
    "Beste 4K TV unter 600€…",
    "Gaming-Maus für FPS-Spiele…",
    "Leichter Laptop für die Uni…",
    "Mechanische Tastatur für das Büro…",
  ],
};

const UI = {
  fr: {
    placeholder: "Décrivez ce que vous recherchez…",
    button: "Rechercher",
    thinking: "Analyse en cours…",
    noResults: "Aucun résultat. Essayez d'autres mots-clés.",
    aiLabel: "Recommandé par IA",
    bestPrice: "Meilleur prix",
    from: "À partir de",
    reviews: "avis",
    viewDeal: "Voir l'offre",
    outOfStock: "Rupture",
    sortByPrice: "Prix croissant",
  },
  en: {
    placeholder: "Describe what you're looking for…",
    button: "Search",
    thinking: "Analyzing…",
    noResults: "No results. Try different keywords.",
    aiLabel: "AI recommended",
    bestPrice: "Best price",
    from: "From",
    reviews: "reviews",
    viewDeal: "View deal",
    outOfStock: "Out of stock",
    sortByPrice: "Price: low to high",
  },
  de: {
    placeholder: "Beschreiben Sie, was Sie suchen…",
    button: "Suchen",
    thinking: "Analyse läuft…",
    noResults: "Keine Ergebnisse. Versuchen Sie andere Suchbegriffe.",
    aiLabel: "KI-Empfehlung",
    bestPrice: "Bester Preis",
    from: "Ab",
    reviews: "Bewertungen",
    viewDeal: "Angebot ansehen",
    outOfStock: "Nicht vorrätig",
    sortByPrice: "Preis aufsteigend",
  },
};

// ── Sub-components ────────────────────────────────────────────────────────────

function Stars({ rating }: { rating: number }) {
  return (
    <div className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((s) => (
        <Star
          key={s}
          className={cn(
            "w-3 h-3",
            s <= Math.round(rating)
              ? "fill-amber-400 text-amber-400"
              : "fill-gray-200 text-gray-200 dark:fill-gray-700 dark:text-gray-700"
          )}
        />
      ))}
    </div>
  );
}

function ResultCard({
  item,
  locale,
  ui,
}: {
  item: SearchResultItem;
  locale: string;
  ui: (typeof UI)["fr"];
}) {
  const locLinks = getLinksForLocale(item.links, locale);
  const visibleLinks = (locLinks.filter((l) => l.in_stock).length > 0
    ? locLinks.filter((l) => l.in_stock)
    : locLinks
  ).slice(0, 5);

  return (
    <div className="flex items-center gap-4 p-4 bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 shadow-sm hover:shadow-md transition-shadow">
      {/* Image */}
      <div className="w-16 h-16 shrink-0 relative rounded-xl overflow-hidden bg-gray-50 dark:bg-gray-800 border border-gray-100 dark:border-gray-700">
        {item.image_url ? (
          <Image
            src={item.image_url}
            alt={item.name}
            fill
            className="object-contain p-1.5"
            sizes="64px"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-2xl text-gray-300">📦</div>
        )}
      </div>

      {/* Name / brand / rating */}
      <div className="flex-1 min-w-0">
        <p className="font-bold text-gray-900 dark:text-gray-100 text-sm leading-snug line-clamp-2">
          {item.name}
        </p>
        {item.brand && (
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">{item.brand}</p>
        )}
        {item.rating != null && (
          <div className="flex items-center gap-1 mt-1.5">
            <Stars rating={item.rating} />
            <span className="text-[10px] text-gray-400 dark:text-gray-500">{item.rating.toFixed(1)}</span>
            {item.review_count > 0 && (
              <span className="text-[10px] text-gray-400 dark:text-gray-500">
                · {item.review_count.toLocaleString()} {ui.reviews}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Price buttons per source */}
      <div className="flex flex-col gap-1.5 shrink-0 items-end">
        {visibleLinks.map((link) => {
          const color = PARTNER_COLORS[link.partner] ?? "#374151";
          const label = PARTNER_LABELS[link.partner] ?? link.partner;
          return (
            <a
              key={link.id}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer sponsored"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-white text-[11px] font-bold transition-opacity hover:opacity-90 whitespace-nowrap"
              style={{ backgroundColor: color }}
            >
              {link.price ? formatPrice(link.price, link.currency, locale) : "—"}
              <span className="opacity-75 font-normal">· {label}</span>
              <ExternalLink className="w-2.5 h-2.5 opacity-60 shrink-0" />
            </a>
          );
        })}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
interface Props {
  locale: string;
}

export function AiSearch({ locale }: Props) {
  const ui = UI[locale as keyof typeof UI] ?? UI.fr;
  const examples = EXAMPLES[locale as keyof typeof EXAMPLES] ?? EXAMPLES.fr;

  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<SearchApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sortByPrice, setSortByPrice] = useState(false);
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  const [placeholderVisible, setPlaceholderVisible] = useState(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Cycle through placeholder examples
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

  const handleSearch = useCallback(async () => {
    if (!query.trim() || loading) return;
    setLoading(true);
    setResponse(null);
    setError(null);
    setSortByPrice(false);
    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), locale }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error ?? `Erreur ${res.status}`);
      } else {
        const parsed = data as SearchApiResponse;
        setResponse(parsed);
        if (parsed.autoSort === "price_asc") setSortByPrice(true);
      }
    } catch {
      setError("Impossible de joindre le serveur. Vérifiez votre connexion.");
    } finally {
      setLoading(false);
    }
  }, [query, locale, loading]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSearch();
    }
  }

  // Auto-resize textarea
  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setQuery(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  return (
    <div className="w-full">
      {/* Search box */}
      <div className="relative w-full max-w-2xl mx-auto">
        <div className="flex items-end gap-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 shadow-lg rounded-2xl px-4 py-3 focus-within:border-emerald-400 dark:focus-within:border-emerald-500 focus-within:ring-2 focus-within:ring-emerald-100 dark:focus-within:ring-emerald-900 transition-all">
          <Search className="w-5 h-5 text-gray-400 shrink-0 mb-0.5" />
          <textarea
            ref={inputRef}
            rows={1}
            value={query}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder={placeholderVisible ? examples[placeholderIdx] : ""}
            className="flex-1 bg-transparent outline-none text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-600 text-base resize-none overflow-hidden leading-6 transition-[placeholder-opacity] duration-300"
            style={{ minHeight: "1.5rem", maxHeight: "8rem" }}
            aria-label={ui.placeholder}
          />
          <button
            onClick={handleSearch}
            disabled={!query.trim() || loading}
            className="shrink-0 p-2 rounded-xl bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors mb-0.5"
            aria-label={ui.button}
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <SendHorizonal className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="mt-6 text-center">
          <div className="inline-flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
            <Sparkles className="w-4 h-4 text-emerald-500 animate-pulse" />
            {ui.thinking}
          </div>
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="mt-6 max-w-2xl mx-auto">
          <div className="flex items-start gap-2 p-4 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 text-sm">
            <span className="font-semibold shrink-0">⚠️ Erreur LLM :</span>
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Results */}
      {response && !loading && (
        <div className="mt-6 max-w-2xl mx-auto">
          {/* Header bar: AI badge + sort */}
          {response.results.length > 0 && (
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs text-emerald-700 dark:text-emerald-400 font-medium">
                {response.fromLLM && <><Sparkles className="w-3.5 h-3.5" />{ui.aiLabel}</>}
              </div>
              <button
                onClick={() => setSortByPrice((v) => !v)}
                className={cn(
                  "flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border transition-colors font-medium",
                  sortByPrice
                    ? "bg-emerald-600 border-emerald-600 text-white"
                    : "border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-emerald-400 hover:text-emerald-600"
                )}
              >
                <ArrowUpDown className="w-3 h-3" />
                {ui.sortByPrice}
              </button>
            </div>
          )}

          {/* No results */}
          {response.results.length === 0 && (
            <p className="text-center text-sm text-gray-500 dark:text-gray-400 py-8">
              {response.message ?? ui.noResults}
            </p>
          )}

          {/* Result cards */}
          <div className="flex flex-col gap-3">
            {(sortByPrice
              ? [...response.results].sort((a, b) => {
                  const minPrice = (item: typeof a) =>
                    Math.min(...item.links.filter((l) => l.price != null).map((l) => l.price!), Infinity);
                  return minPrice(a) - minPrice(b);
                })
              : response.results
            ).map((item) => (
              <ResultCard
                key={item.id}
                item={item}
                locale={locale}
                ui={ui}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
