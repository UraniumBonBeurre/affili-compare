import Image from "next/image";
import type { Locale } from "@/types/database";

interface ProductTileProps {
  id: string;
  name: string;
  brand: string | null;
  image_url: string | null;
  price: number | null;
  currency: string | null;
  affiliate_url: string | null;
  locale: Locale;
}

function formatPrice(price: number | null, currency: string | null, locale: Locale): string {
  if (!price) return "";
  const sym = currency?.toUpperCase() === "GBP" ? "£" : currency?.toUpperCase() === "USD" ? "$" : "€";
  return locale === "en"
    ? `${sym}${price.toFixed(2).replace(/\.00$/, "")}`
    : `${price.toFixed(2).replace(/\.00$/, "").replace(".", ",")} ${sym}`;
}

export function ProductTile({ name, brand, image_url, price, currency, affiliate_url, locale }: ProductTileProps) {
  const priceStr = formatPrice(price, currency, locale);

  const inner = (
    <div className="group h-full bg-white/80 backdrop-blur-sm rounded-2xl border border-white/60 hover:border-stone-300/80 shadow-sm hover:shadow-lg transition-all duration-200 flex flex-col overflow-hidden">
      {/* Image */}
      <div className="aspect-square bg-stone-50 flex items-center justify-center p-3 overflow-hidden">
        {image_url ? (
          <Image
            src={image_url}
            alt={name}
            width={180}
            height={180}
            className="object-contain w-full h-full group-hover:scale-[1.04] transition-transform duration-300"
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
            unoptimized
          />
        ) : (
          <div className="w-full h-full bg-stone-100 rounded-xl" />
        )}
      </div>

      {/* Info */}
      <div className="flex-1 flex flex-col px-3 pb-3 pt-2">
        {brand && (
          <p className="text-[10px] font-bold uppercase tracking-wider text-stone-400 mb-0.5 truncate">
            {brand}
          </p>
        )}
        <p className="text-xs sm:text-[13px] font-medium text-stone-700 leading-snug mb-2 line-clamp-3 flex-1">
          {name}
        </p>
        {priceStr && (
          <p className="text-sm font-extrabold text-amber-600 mb-2">{priceStr}</p>
        )}
        {affiliate_url && (
          <span className="inline-block text-center w-full bg-stone-800 hover:bg-stone-700 text-white rounded-xl text-[11px] font-semibold px-2 py-1.5 transition-colors">
            {locale === "en" ? "View deal →" : "Voir le produit →"}
          </span>
        )}
      </div>
    </div>
  );

  if (affiliate_url) {
    return (
      <a href={affiliate_url} target="_blank" rel="noopener noreferrer sponsored" className="block h-full">
        {inner}
      </a>
    );
  }
  return <div className="h-full">{inner}</div>;
}
