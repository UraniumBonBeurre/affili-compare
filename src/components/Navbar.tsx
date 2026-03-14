import Link from "next/link";
import { LocaleSwitcher } from "./LocaleSwitcher";
import type { Locale } from "@/types/database";

export function Navbar({ locale }: { locale: Locale }) {
  return (
    <header className="sticky top-0 z-[60] bg-amber-50/80 backdrop-blur-xl border-b border-amber-100/60">
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-center relative">
        {/* Centered logo */}
        <Link href={`/${locale}`} className="font-playfair font-semibold text-2xl tracking-wide">
          <span className="text-amber-700">My</span>
          <span className="text-stone-600">GoodPick</span>
        </Link>

        {/* Locale switcher — absolute right */}
        <div className="absolute right-4 flex items-center">
          <LocaleSwitcher locale={locale} />
        </div>
      </div>
    </header>
  );
}
