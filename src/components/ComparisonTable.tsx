"use client";

import { useState } from "react";
import Image from "next/image";
import { ExternalLink, Star } from "lucide-react";
import { cn } from "@/lib/utils";
import { PARTNER_COLORS, PARTNER_LABELS, getLinksForLocale, cheapestLink, formatPrice } from "@/lib/affiliate-links";
import type { ProductWithLinks, Locale } from "@/types/database";

interface ComparisonTableProps {
  products: ProductWithLinks[];
  locale:   Locale;
}

const RANK_STYLE: Record<number, string> = {
  1: "bg-amber-400 text-white",
  2: "bg-gray-300 text-gray-700",
  3: "bg-amber-600/70 text-white",
};

function Stars({ rating, reviewCount }: { rating: number | null; reviewCount?: number }) {
  if (rating == null) {
    return <p className="text-[10px] text-gray-400 italic">Aucune évaluation</p>;
  }
  return (
    <div className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((s) => (
        <Star
          key={s}
          className={cn(
            "w-3 h-3",
            s <= Math.round(rating) ? "fill-amber-400 text-amber-400" : "fill-gray-200 text-gray-200"
          )}
        />
      ))}
      <span className="ml-1 text-xs font-semibold text-gray-600">{rating.toFixed(1)}</span>
      {reviewCount != null && reviewCount > 0 && (
        <span className="ml-0.5 text-[10px] text-gray-400">({reviewCount.toLocaleString()})</span>
      )}
    </div>
  );
}

function ReleaseDate({ date }: { date: string | null }) {
  if (!date) return null;
  try {
    const d = new Date(date);
    const label = d.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
    return <p className="text-[10px] text-gray-400 mt-0.5">Sorti en {label}</p>;
  } catch {
    return null;
  }
}

function PriceButton({
  link,
  isCheapest,
  locale,
}: {
  link: { id: string; partner: string; price: number | null; currency: string; url: string; in_stock: boolean };
  isCheapest: boolean;
  locale: Locale;
}) {
  const color = PARTNER_COLORS[link.partner] ?? "#374151";
  const label = PARTNER_LABELS[link.partner] ?? link.partner;

  return (
    <a
      href={link.url}
      target="_blank"
      rel="noopener noreferrer sponsored"
      className={cn(
        "flex flex-col items-center px-3 py-2 rounded-xl text-white text-xs font-bold min-w-[90px]",
        isCheapest && "ring-2 ring-offset-1 ring-emerald-400 shadow-md"
      )}
      style={{ backgroundColor: color }}
    >
      <span className="opacity-90 font-medium">{label}</span>
      <span className="text-sm font-extrabold mt-0.5 flex items-center gap-1">
        {link.price ? formatPrice(link.price, link.currency, locale) : "—"}
        <ExternalLink className="w-2.5 h-2.5 opacity-60" />
      </span>
      {isCheapest && (
        <span className="text-[9px] font-bold uppercase tracking-wide opacity-90 mt-0.5">
          Meilleur prix
        </span>
      )}
    </a>
  );
}

function ProductRow({
  product,
  locale,
  rank,
}: {
  product: ProductWithLinks;
  locale:  Locale;
  rank:    number;
}) {
  const links    = getLinksForLocale(product.links, locale);
  const cheapest = cheapestLink(links);

  return (
    <tr className="border-b border-gray-100 last:border-0 hover:bg-gray-50/60 transition-colors">
      {/* Rang */}
      <td className="py-4 pl-4 pr-3 text-center align-middle w-10">
        <span className={cn("inline-flex w-7 h-7 rounded-full items-center justify-center text-xs font-black", RANK_STYLE[rank] ?? "bg-gray-100 text-gray-500")}>
          {rank}
        </span>
      </td>

      {/* Image */}
      <td className="py-4 pr-4 align-middle w-20">
        <div className="w-16 h-16 relative rounded-lg overflow-hidden bg-gray-50 border border-gray-100 shrink-0">
          {product.image_url ? (
            <Image src={product.image_url} alt={product.name} fill className="object-contain p-1.5" sizes="64px" />
          ) : (
            <div className="flex items-center justify-center h-full text-2xl">📦</div>
          )}
        </div>
      </td>

      {/* Produit */}
      <td className="py-4 pr-6 align-middle min-w-[180px]">
        <p className="text-[10px] font-bold uppercase tracking-widest text-gray-400 mb-0.5">{product.brand}</p>
        <p className="font-bold text-gray-900 text-sm leading-snug mb-1">{product.name}</p>
        <Stars rating={product.rating} reviewCount={product.review_count} />
        <ReleaseDate date={product.release_date ?? null} />
      </td>

      {/* Meilleur prix */}
      <td className="py-4 pr-6 align-middle w-28">
        {cheapest?.price ? (
          <div>
            <p className="text-xl font-black text-gray-900">{formatPrice(cheapest.price, cheapest.currency, locale)}</p>
            <p className="text-[10px] text-gray-400">chez {PARTNER_LABELS[cheapest.partner] ?? cheapest.partner}</p>
          </div>
        ) : (
          <span className="text-xs text-gray-400">N/D</span>
        )}
      </td>

      {/* Sources (boutons marchands) */}
      <td className="py-4 pr-4 align-middle">
        <div className="flex flex-wrap gap-2">
          {links.filter((l) => l.in_stock).map((link) => (
            <PriceButton
              key={link.id}
              link={link}
              isCheapest={link.id === cheapest?.id}
              locale={locale}
            />
          ))}
          {!links.some((l) => l.in_stock) && (
            <span className="text-xs text-gray-400 italic">Rupture de stock</span>
          )}
        </div>
      </td>
    </tr>
  );
}

export function ComparisonTable({ products, locale }: ComparisonTableProps) {
  const [sort, setSort] = useState<"position" | "price" | "rating" | "score">("position");

  const sorted = [...products].sort((a, b) => {
    if (sort === "price") {
      const pa = Math.min(...(a.links.filter((l) => l.price).map((l) => l.price!) ?? [Infinity]));
      const pb = Math.min(...(b.links.filter((l) => l.price).map((l) => l.price!) ?? [Infinity]));
      return (pa ?? Infinity) - (pb ?? Infinity);
    }
    if (sort === "rating") {
      return (b.rating ?? 0) - (a.rating ?? 0);
    }
    if (sort === "score") {
      // Score = note 60% + (prix inversé normalisé) 40%
      const prices = products.map((p) => Math.min(...(p.links.filter((l) => l.price).map((l) => l.price!) ?? [Infinity])));
      const maxP   = Math.max(...prices.filter((p) => p !== Infinity));
      const minP   = Math.min(...prices.filter((p) => p !== Infinity));
      const range  = maxP - minP || 1;
      const priceScore = (x: number) => x === Infinity ? 0 : 1 - (x - minP) / range;
      const pa = Math.min(...(a.links.filter((l) => l.price).map((l) => l.price!) ?? [Infinity]));
      const pb = Math.min(...(b.links.filter((l) => l.price).map((l) => l.price!) ?? [Infinity]));
      const sa = (a.rating ?? 0) / 5 * 0.6 + priceScore(pa) * 0.4;
      const sb2 = (b.rating ?? 0) / 5 * 0.6 + priceScore(pb) * 0.4;
      return sb2 - sa;
    }
    return 0; // keep original position
  });

  const SORTS = [
    { key: "position" as const, label: "Classement" },
    { key: "price"    as const, label: "Prix ↑" },
    { key: "rating"   as const, label: "Note ↓" },
    { key: "score"    as const, label: "Meilleur rapport" },
  ];

  return (
    <div>
      {/* Sort bar */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className="text-xs text-gray-400 font-medium mr-1">Trier par :</span>
        {SORTS.map((s) => (
          <button
            key={s.key}
            onClick={() => setSort(s.key)}
            className={cn(
              "px-3 py-1 rounded-full text-xs font-semibold transition-colors border",
              sort === s.key
                ? "bg-emerald-600 text-white border-emerald-600"
                : "bg-white text-gray-600 border-gray-200 hover:border-emerald-400"
            )}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="w-full overflow-x-auto rounded-2xl border border-gray-100 shadow-sm bg-white">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-gray-100 text-xs font-bold uppercase tracking-wider text-gray-400 bg-gray-50">
              <th className="py-3 pl-4 pr-3 text-center">#</th>
              <th className="py-3 pr-4"></th>
              <th className="py-3 pr-6 text-left">Produit</th>
              <th className="py-3 pr-6 text-left">Meilleur prix</th>
              <th className="py-3 pr-4 text-left">Où acheter</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((product, idx) => (
              <ProductRow key={product.id} product={product} locale={locale} rank={idx + 1} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

