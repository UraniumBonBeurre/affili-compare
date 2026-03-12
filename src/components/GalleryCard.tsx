"use client";

import { useState } from "react";
import Link from "next/link";

interface Props {
  slug: string;
  title: string;
  subcategory: string;
  pinImages: string[];
  locale: string;
}

function firstUsableUrl(images: string[]): string | null {
  return images.find((u) => u.startsWith("http") || u.startsWith("/")) ?? null;
}

export function GalleryCard({ slug, title, subcategory, pinImages, locale }: Props) {
  const [imgFailed, setImgFailed] = useState(false);
  const bgUrl = firstUsableUrl(pinImages);
  const showImg = bgUrl && !imgFailed;

  return (
    <Link href={`/${locale}/top/${slug}`} className="group block">
      <div className="relative aspect-square rounded-2xl overflow-hidden bg-stone-100 cursor-pointer ring-1 ring-stone-200/60 hover:ring-stone-400/60 transition-all duration-300 shadow-sm hover:shadow-lg">

        {/* Background image */}
        {showImg && (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={bgUrl}
            alt={title}
            onError={() => setImgFailed(true)}
            className="absolute inset-0 w-full h-full object-cover group-hover:scale-[1.04] transition-transform duration-500"
          />
        )}

        {/* Gradient fallback */}
        {!showImg && (
          <div className="absolute inset-0 bg-gradient-to-br from-stone-200 via-stone-100 to-stone-50" />
        )}

        {/* Bottom gradient overlay for text legibility */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />

        {/* Top shimmer on hover */}
        <div className="absolute inset-0 bg-gradient-to-b from-white/0 to-white/0 group-hover:from-white/10 transition-all duration-300" />

        {/* Content */}
        <div className="absolute bottom-0 left-0 right-0 p-4">
          {subcategory && (
            <span className="inline-block text-[10px] font-bold text-amber-300 uppercase tracking-wider mb-1.5 drop-shadow-sm">
              {subcategory}
            </span>
          )}
          <p className="text-white font-bold text-sm leading-snug line-clamp-2 drop-shadow-sm">
            {title}
          </p>
        </div>
      </div>
    </Link>
  );
}
