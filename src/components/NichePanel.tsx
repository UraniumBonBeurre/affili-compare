"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { SiteCategory } from "@/lib/site-categories";
import type { Locale } from "@/types/database";

interface Props {
  category: SiteCategory;
  locale: Locale;
}

export function NichePanel({ category, locale }: Props) {
  const pathname = usePathname();
  const isEn = locale === "en";
  const categoryName = isEn ? category.name_en : category.name;

  return (
    <div className="h-full flex flex-col bg-white/10 backdrop-blur-md border-r border-white/20">
      {/* Category header — back link */}
      <div className="flex-none px-3 pt-5 pb-4 border-b border-white/15">
        <Link
          href={`/${locale}/${category.id}`}
          className="group flex items-center gap-2 hover:bg-white/10 rounded-xl px-2 py-2 transition-colors"
        >
          <span className="text-white/50 group-hover:text-white/80 text-sm transition-colors">←</span>
          <div>
            <div className="text-white/50 text-[10px] uppercase tracking-widest font-semibold group-hover:text-white/70 transition-colors">
              {isEn ? "Category" : "Catégorie"}
            </div>
            <div className="font-playfair font-bold text-white text-sm leading-tight">
              {category.icon} {categoryName}
            </div>
          </div>
        </Link>
      </div>

      {/* Niche list */}
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
        {category.niches.map((niche) => {
          const href = `/${locale}/${category.id}/${niche.slug}`;
          const isActive = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={niche.slug}
              href={href}
              className={`
                flex items-center justify-between gap-2 px-3 py-2.5 rounded-xl text-sm transition-all duration-150
                ${isActive
                  ? "bg-white/20 text-white font-semibold shadow-sm"
                  : "text-white/70 hover:text-white hover:bg-white/10 font-normal"
                }
              `}
            >
              <span className="leading-tight">
                {isEn ? niche.name_en : niche.name}
              </span>
              {isActive && <span className="text-white/60 text-xs">•</span>}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
