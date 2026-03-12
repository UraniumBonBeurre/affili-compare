/**
 * Top5Section — Sélections du mois avec filtre par univers et panneau de détail.
 * - Dropdown pour filtrer par univers (Salon, Gaming, Bureau, Audio, Mobile)
 * - Clic sur une carte → scroll vers un panneau encadré qui affiche le Top 5
 */

"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { ExternalLink, Star, X, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface Top5Product {
  id: string;
  name: string;
  brand: string | null;
  price: number | null;
  url: string | null;
  image_url: string | null;
  rating: number | null;
  blurb_fr: string;
}

interface Top5Article {
  id: string;
  slug: string;
  category_slug: string;
  subcategory: string;
  title_fr: string;
  intro_fr: string | null;
  products: Top5Product[];
  month: string;
}

// ── Définition des univers ────────────────────────────────────────────────────
const THEMES = [
  { key: "tout",   label: "Tout",    icon: "⭐" },
  { key: "salon",  label: "Salon",   icon: "🛋️" },
  { key: "audio",  label: "Audio",   icon: "🎧" },
  { key: "gaming", label: "Gaming",  icon: "🎮" },
  { key: "bureau", label: "Bureau",  icon: "💼" },
  { key: "mobile", label: "Mobile",  icon: "📱" },
] as const;

type ThemeKey = (typeof THEMES)[number]["key"];

function getTheme(article: Top5Article): ThemeKey {
  const cat = article.category_slug;
  const sub = article.subcategory.toLowerCase();
  if (cat === "gaming") return "gaming";
  if (cat === "informatique") return "bureau";
  if (cat === "smartphone") return "mobile";
  if (sub.includes("télé") || sub.includes("tv") || sub.includes("enceinte")) return "salon";
  if (sub.includes("casque") || sub.includes("audio")) return "audio";
  return "tout";
}

const CATEGORY_ICONS: Record<string, string> = {
  "tv-hifi":      "📺",
  "gaming":       "🎮",
  "informatique": "💻",
  "smartphone":   "📱",
};

// ── Composant principal ───────────────────────────────────────────────────────
interface Props {
  locale?: string;
}

export function Top5Section({ locale = "fr" }: Props) {
  const [articles, setArticles]   = useState<Top5Article[]>([]);
  const [filter, setFilter]       = useState<ThemeKey>("tout");
  const [selected, setSelected]   = useState<Top5Article | null>(null);
  const detailRef                 = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`/api/top5?locale=${locale}&limit=20`)
      .then((r) => r.json())
      .then((data) => {
        if (data.articles) {
          const parsed: Top5Article[] = data.articles.map(
            (a: Top5Article & { products: string | Top5Product[] }) => ({
              ...a,
              products:
                typeof a.products === "string"
                  ? JSON.parse(a.products)
                  : a.products,
            })
          );
          setArticles(parsed);
        }
      })
      .catch(() => {/* section simplement masquée si échec */});
  }, [locale]);

  // Univers disponibles parmi les articles chargés
  const availableThemes = THEMES.filter(
    (t) => t.key === "tout" || articles.some((a) => getTheme(a) === t.key)
  );

  const filtered =
    filter === "tout"
      ? articles
      : articles.filter((a) => getTheme(a) === filter);

  function handleSelect(article: Top5Article) {
    if (selected?.slug === article.slug) {
      setSelected(null);
      return;
    }
    setSelected(article);
    setTimeout(() => {
      detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 60);
  }

  if (!articles.length) return null;

  return (
    <section className="mb-16">
      {/* ── En-tête + dropdown ── */}
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 mb-5">
        <div>
          <h2 className="text-xl font-extrabold text-gray-900 dark:text-white">
            Sélections du mois
          </h2>
          <p className="text-sm text-gray-400 dark:text-gray-500">
            Top 5 des produits les mieux notés, mis à jour chaque mois.
          </p>
        </div>

        {/* Dropdown univers */}
        <div className="relative shrink-0">
          <select
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value as ThemeKey);
              setSelected(null);
            }}
            className="appearance-none pl-3 pr-8 py-2 rounded-xl border border-stone-200 bg-white/70 backdrop-blur-sm text-sm font-medium text-stone-700 cursor-pointer focus:ring-2 focus:ring-stone-400 focus:outline-none shadow-sm"
          >
            {availableThemes.map((t) => (
              <option key={t.key} value={t.key}>
                {t.icon} {t.label}
              </option>
            ))}
          </select>
          <ChevronDown
            size={14}
            className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400"
          />
        </div>
      </div>

      {/* ── Grille de cartes ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {filtered.map((article) => {
          const isActive = selected?.slug === article.slug;
          const icon = CATEGORY_ICONS[article.category_slug] ?? "🛒";

          return (
            <button
              key={article.slug}
              onClick={() => handleSelect(article)}
              className={cn(
                "flex items-center gap-3 p-4 rounded-xl bg-white dark:bg-gray-900 border shadow-sm text-left transition-all",
                isActive
                  ? "border-stone-500 ring-2 ring-stone-200"
                  : "border-stone-100 hover:border-stone-300 hover:shadow"
              )}
            >
              <span className="text-xl shrink-0">{icon}</span>
              <div className="min-w-0 flex-1">
                <p className="text-xs text-gray-400 dark:text-gray-500 truncate">
                  {article.subcategory}
                </p>
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 line-clamp-2">
                  {article.title_fr}
                </p>
              </div>
              {isActive && (
                <span className="shrink-0 w-5 h-5 rounded-full bg-stone-700 text-white flex items-center justify-center">
                  <X size={11} />
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* ── Panneau de détail (scroll-target) ── */}
      {selected && (
        <div
          ref={detailRef}
          className="mt-8 rounded-2xl bg-white/80 backdrop-blur-sm border-2 border-stone-300 shadow-xl overflow-hidden scroll-mt-8"
        >
          {/* Header du panneau */}
          <div className="flex items-start justify-between gap-4 px-6 py-5 border-b border-stone-100 bg-stone-50/50">
            <div>
              <p className="text-xs font-semibold text-stone-500 uppercase tracking-wide mb-1">
                {selected.subcategory}
              </p>
              <h3 className="text-lg font-extrabold text-gray-900 dark:text-white leading-tight">
                {selected.title_fr}
              </h3>
              {selected.intro_fr && (
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 italic">
                  {selected.intro_fr}
                </p>
              )}
              <a
                href={`/${locale}/top/${selected.slug}`}
                className="inline-block mt-3 text-xs font-semibold text-stone-600 hover:underline"
              >
                Lire l&apos;article complet →
              </a>
            </div>
            <button
              onClick={() => setSelected(null)}
              aria-label="Fermer"
              className="shrink-0 p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            >
              <X size={18} />
            </button>
          </div>

          {/* Liste des 5 produits */}
          <ol className="divide-y divide-gray-100 dark:divide-gray-800">
            {selected.products.map((product, idx) => (
              <li key={product.id} className="flex gap-4 items-start px-6 py-5">
                {/* Rang */}
                <span className="shrink-0 w-7 h-7 mt-0.5 rounded-full bg-stone-100 text-stone-700 text-sm font-bold flex items-center justify-center">
                  {idx + 1}
                </span>

                {/* Image */}
                {product.image_url && (
                  <div className="shrink-0 w-16 h-16 rounded-xl overflow-hidden bg-gray-100 dark:bg-gray-800">
                    <Image
                      src={product.image_url}
                      alt={product.name}
                      width={64}
                      height={64}
                      className="w-full h-full object-contain"
                      unoptimized
                    />
                  </div>
                )}

                {/* Infos produit */}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 leading-snug">
                    {product.name}
                  </p>
                  {product.blurb_fr && (
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">
                      {product.blurb_fr}
                    </p>
                  )}
                  <div className="flex flex-wrap items-center gap-3 mt-2">
                    {product.rating != null && (
                      <span className="flex items-center gap-0.5 text-xs text-amber-500 font-medium">
                        <Star size={11} fill="currentColor" />
                        {product.rating}
                      </span>
                    )}
                    {product.price != null && (
                      <span className="text-sm font-extrabold text-stone-700">
                        {product.price}€
                      </span>
                    )}
                    {product.url && (
                      <a
                        href={product.url}
                        target="_blank"
                        rel="noopener noreferrer sponsored"
                        className="ml-auto flex items-center gap-1 text-xs font-semibold text-white bg-stone-700 hover:bg-stone-600 px-3 py-1.5 rounded-lg transition-colors shrink-0"
                      >
                        Voir l&apos;offre <ExternalLink size={11} />
                      </a>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
