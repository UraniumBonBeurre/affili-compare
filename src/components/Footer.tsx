import Link from "next/link";
import type { Locale } from "@/types/database";

const t = {
  fr: { legal: "Mentions légales", privacy: "Confidentialité", affiliate: "Liens affiliés" },
  en: { legal: "Legal",            privacy: "Privacy",          affiliate: "Affiliate links" },
};

export function Footer({ locale }: { locale: Locale }) {
  const l = t[locale] ?? t.fr;
  return (
    <footer className="mt-20 border-t border-stone-200/40 bg-white/40 backdrop-blur-sm">
      <div className="max-w-6xl mx-auto px-4 py-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-stone-400">
        <p>© {new Date().getFullYear()} MyGoodPick — {locale === "en" ? "Compare before you buy" : "Comparez avant d'acheter"}</p>
        <nav className="flex gap-5">
          <Link href={`/${locale}/legal`}   className="hover:text-stone-600 transition-colors">{l.legal}</Link>
          <Link href={`/${locale}/privacy`} className="hover:text-stone-600 transition-colors">{l.privacy}</Link>
          <span className="text-stone-300">·</span>
          <span className="text-stone-400">{l.affiliate}</span>
        </nav>
      </div>
    </footer>
  );
}
