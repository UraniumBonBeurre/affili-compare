"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LOCALES = [
  { code: "fr", flag: "🇫🇷", label: "FR" },
  { code: "en", flag: "🇬🇧", label: "EN" },
  { code: "de", flag: "🇩🇪", label: "DE" },
] as const;

export function LocaleSwitcher({ locale }: { locale: string }) {
  const pathname = usePathname(); // e.g. "/fr/informatique/meilleures-souris"

  function getHref(targetCode: string) {
    // segments: ["", "fr", "informatique", ...]
    const segments = pathname.split("/");
    segments[1] = targetCode;
    return segments.join("/");
  }

  return (
    <div className="flex items-center gap-1">
      {LOCALES.map(({ code, flag, label }) => (
        <Link
          key={code}
          href={getHref(code)}
          className={`px-2 py-1 text-xs rounded-md font-medium transition-colors ${
            code === locale
              ? "bg-emerald-600 text-white"
              : "text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
          }`}
        >
          {flag} {label}
        </Link>
      ))}
    </div>
  );
}
