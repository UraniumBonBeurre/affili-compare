
import Link from "next/link";
import { LocaleSwitcher } from "./LocaleSwitcher";
import { ThemeToggle } from "./ThemeToggle";
import type { Locale } from "@/types/database";

export function Navbar({ locale }: { locale: Locale }) {
  return (
    <header className="sticky top-0 z-40 bg-white dark:bg-gray-950 border-b border-gray-100 dark:border-gray-800 shadow-sm">
      <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between gap-4">
        <Link href={`/${locale}`} className="font-black text-xl tracking-tight">
          <span className="text-emerald-600">My</span>
          <span className="text-gray-900 dark:text-white">GoodPick</span>
        </Link>
        <div className="flex items-center gap-2">
          <LocaleSwitcher locale={locale} />
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
