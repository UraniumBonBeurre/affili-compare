"use client";

import { useState } from "react";

interface Product {
  id?: string;
  name: string;
  brand: string | null;
  price: number | null;
  url: string | null;
  image_url: string | null;
  blurb_fr?: string;
}

interface Props {
  product: Product;
  rank: number;
  offerLabel: string;
  locale: string;
}

export function ProductCard({ product: p, rank, offerLabel, locale }: Props) {
  const [imgFailed, setImgFailed] = useState(false);
  const showImg = p.image_url && !imgFailed;

  const priceStr = p.price != null
    ? locale === "en"
      ? `€${p.price.toFixed(2)}`
      : `${p.price.toFixed(2)} €`
    : null;

  return (
    <div className="group relative flex flex-col bg-white/80 backdrop-blur-sm rounded-2xl border border-stone-200/60 hover:border-stone-300 shadow-sm hover:shadow-lg transition-all overflow-hidden">
      {/* Image area */}
      <div className="relative aspect-square bg-stone-50 overflow-hidden">
        {showImg ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={p.image_url!}
            alt={p.name}
            className="w-full h-full object-contain p-3 group-hover:scale-105 transition-transform duration-300"
            onError={() => setImgFailed(true)}
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <svg
              className="w-10 h-10 text-stone-300"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1}
                d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
              />
            </svg>
          </div>
        )}
        {/* Rank badge */}
        <span className="absolute top-2 left-2 w-5 h-5 flex items-center justify-center rounded-full bg-stone-700 text-white text-[10px] font-bold shadow">
          {rank}
        </span>
      </div>

      {/* Content */}
      <div className="flex flex-col flex-1 p-3 gap-1.5">
        {p.brand && (
          <p className="text-[10px] font-semibold text-stone-500 uppercase tracking-wide truncate">
            {p.brand}
          </p>
        )}
        <p className="text-xs sm:text-sm font-bold text-stone-800 leading-snug line-clamp-2 flex-1">
          {p.name}
        </p>
        {p.blurb_fr && (
          <p className="text-[10px] text-stone-400 leading-relaxed line-clamp-2 hidden sm:block">
            {p.blurb_fr}
          </p>
        )}
        {priceStr && (
          <p className="text-base font-extrabold text-stone-700 mt-0.5">
            {priceStr}
          </p>
        )}
        {p.url && (
          <a
            href={p.url}
            target="_blank"
            rel="noopener noreferrer nofollow sponsored"
            className="mt-1 text-center text-xs px-3 py-2 bg-stone-800 hover:bg-stone-700 active:bg-stone-900 text-white rounded-xl font-semibold transition-colors"
          >
            {offerLabel}
          </a>
        )}
      </div>
    </div>
  );
}
