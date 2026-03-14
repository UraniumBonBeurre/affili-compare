"use client";

import { useState } from "react";
import Link from "next/link";

interface Props {
  slug: string;
  title: string;
  subcategory: string;
  pinImages: string[];
  locale: string;
  onOpen?: (slug: string) => void;
  aspectClass?: string;
}

function firstUsableUrl(images: string[]): string | null {
  return images.find((u) => u.startsWith("http") || u.startsWith("/")) ?? null;
}

export function GalleryCard({ slug, title, subcategory, pinImages, locale, onOpen, aspectClass = "aspect-square" }: Props) {
  const [imgFailed, setImgFailed] = useState(false);
  const bgUrl = firstUsableUrl(pinImages);
  const showImg = bgUrl && !imgFailed;

  const inner = (
    <div className={`relative ${aspectClass} rounded-2xl overflow-hidden bg-stone-100 cursor-pointer ring-1 ring-stone-200/60 hover:ring-stone-400/60 transition-all duration-300 shadow-sm hover:shadow-lg`}>
      {showImg && (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img src={bgUrl} alt={title} onError={() => setImgFailed(true)}
          className="absolute inset-0 w-full h-full object-cover group-hover:scale-[1.04] transition-transform duration-500" />
      )}
      {!showImg && (
        <div className="absolute inset-0 bg-gradient-to-br from-stone-200 via-stone-100 to-stone-50" />
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />
      <div className="absolute inset-0 bg-gradient-to-b from-white/0 to-white/0 group-hover:from-white/10 transition-all duration-300" />
      <div className="absolute bottom-0 left-0 right-0 p-4 pb-5">
        {subcategory && (
          <span className="inline-block text-sm font-bold text-amber-300 uppercase tracking-wider mb-2 drop-shadow">
            {subcategory}
          </span>
        )}
        <p className="font-sans font-extrabold text-white text-[17px] leading-snug [text-shadow:0_1px_6px_rgba(0,0,0,0.9)]">{title}</p>
      </div>
    </div>
  );

  if (onOpen) {
    return (
      <button className="group block w-full text-left" onClick={() => onOpen(slug)}>
        {inner}
      </button>
    );
  }

  return (
    <Link href={`/${locale}/top/${slug}`} className="group block">
      {inner}
    </Link>
  );
}
