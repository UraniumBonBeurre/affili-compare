import Link from "next/link";
import { useTranslations } from "next-intl";
import type { Locale } from "@/types/database";

export function Footer({ locale }: { locale: Locale }) {
  const t = useTranslations("footer");
  const st = useTranslations("site");

  return (
    <footer className="mt-16 border-t border-gray-200 bg-gray-50">
      <div className="max-w-5xl mx-auto px-4 py-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-gray-500">
        <p>© {new Date().getFullYear()} {st("name")} — {st("tagline")}</p>
        <nav className="flex gap-4">
          <Link href={`/${locale}/legal`} className="hover:text-gray-800 transition-colors">{t("legal")}</Link>
          <Link href={`/${locale}/privacy`} className="hover:text-gray-800 transition-colors">{t("privacy")}</Link>
          <span className="text-gray-300">|</span>
          <span className="text-xs text-gray-400">{t("affiliate")}</span>
        </nav>
      </div>
    </footer>
  );
}
