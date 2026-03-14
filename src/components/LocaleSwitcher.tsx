"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LOCALES = [
  { code: "fr", label: "🇫🇷" },
  { code: "en", label: "🇬🇧" },
] as const;

export function LocaleSwitcher({ locale }: { locale: string }) {
  const pathname = usePathname();

  function getHref(targetCode: string) {
    const segments = pathname.split("/");
    segments[1] = targetCode;
    return segments.join("/");
  }

  return (
    <div className="flex items-center gap-1 bg-stone-100/80 rounded-lg p-0.5">
      {LOCALES.map(({ code, label }) => (
        <Link
          key={code}
          href={getHref(code)}
          className={`px-2 py-1 text-base rounded-md transition-all ${
            code === locale
              ? "bg-amber-500 shadow-sm scale-110"
              : "opacity-50 hover:opacity-80"
          }`}
        >
          {label}
        </Link>
      ))}
    </div>
  );
}
