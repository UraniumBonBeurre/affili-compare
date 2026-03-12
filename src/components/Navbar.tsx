import Link from "next/link";
import { LocaleSwitcher } from "./LocaleSwitcher";
import type { Locale } from "@/types/database";

export function Navbar({ locale }: { locale: Locale }) {
  return (
    <header className="sticky top-0 z-40 bg-white/70 backdrop-blur-xl border-b border-stone-200/40">
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-center relative">
        {/* Centered logo */}
        <Link href={`/${locale}`} className="font-playfair font-semibold text-2xl tracking-wide">
          <span className="text-stone-800">My</span>
          <span className="text-stone-500">GoodPick</span>
        </Link>

        {/* Locale switcher — absolute right */}
        <div className="absolute right-4 flex items-center">
          <LocaleSwitcher locale={locale} />
        </div>
      </div>
    </header>
  );
}
