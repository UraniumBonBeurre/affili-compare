"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LOCALES = [
  { code: "fr", label: "FR" },
  { code: "en", label: "EN" },
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
          className={`px-2.5 py-1 text-xs rounded-md font-semibold transition-colors ${
            code === locale
              ? "bg-stone-700 text-white shadow-sm"
              : "text-stone-400 hover:text-stone-700"
          }`}
        >
          {label}
        </Link>
      ))}
    </div>
  );
}
