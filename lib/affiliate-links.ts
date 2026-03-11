import type { AffiliateLink, Locale } from "@/types/database";
import merchantsJson from "@/config/merchants.json";

type MerchantDef = {
  key: string;
  label: string;
  color: string;
  network: string;
  country: string;
  locale_affinity: string[];
  active: boolean;
  awin_programme_id?: string;
};

const ALL_MERCHANTS = merchantsJson.merchants as unknown as MerchantDef[];

/** Couleur CSS associée à chaque partenaire affilié (dérivé de config/merchants.json) */
export const PARTNER_COLORS: Record<string, string> = Object.fromEntries(
  ALL_MERCHANTS.map((m) => [m.key, m.color])
);

/** Nom lisible par partenaire (dérivé de config/merchants.json) */
export const PARTNER_LABELS: Record<string, string> = Object.fromEntries(
  ALL_MERCHANTS.map((m) => [m.key, m.label])
);

/** Filtre les liens affiliés selon la locale du visiteur */
export function getLinksForLocale(
  links: AffiliateLink[],
  locale: Locale
): AffiliateLink[] {
  // Récupère les pays ciblant cette locale, dés le config
  const allowedCountries = Array.from(
    new Set(
      ALL_MERCHANTS
        .filter((m) => m.locale_affinity.includes(locale))
        .map((m) => m.country)
    )
  );
  const localeLinks = links.filter(
    (l) => allowedCountries.includes(l.country) && l.in_stock
  );
  // Fallback : si aucun lien pour la locale, retourne tous les liens en stock
  return localeLinks.length > 0 ? localeLinks : links.filter((l) => l.in_stock);
}

/** Retourne le lien le moins cher parmi une liste */
export function cheapestLink(links: AffiliateLink[]): AffiliateLink | null {
  if (!links.length) return null;
  return links.reduce((best, l) =>
    (l.price ?? Infinity) < (best.price ?? Infinity) ? l : best
  );
}

/** Formate un prix avec locale et devise */
export function formatPrice(price: number, currency: string, locale: Locale): string {
  const localeStr = locale === "de" ? "de-DE" : locale === "en" ? "en-GB" : "fr-FR";
  return new Intl.NumberFormat(localeStr, {
    style:    "currency",
    currency: currency ?? "EUR",
    minimumFractionDigits: 2,
  }).format(price);
}

/** Génère un lien Amazon avec tag associé + paramètre de tracking */
export function buildAmazonUrl(asin: string, locale: Locale): string {
  const tagMap: Record<Locale, string> = {
    fr: process.env.AMAZON_ASSOCIATE_TAG_FR ?? "afprod-21",
    en: process.env.AMAZON_ASSOCIATE_TAG_UK ?? "",
    de: process.env.AMAZON_ASSOCIATE_TAG_DE ?? "",
  };
  const domainMap: Record<Locale, string> = {
    fr: "amazon.fr",
    en: "amazon.co.uk",
    de: "amazon.de",
  };
  return `https://www.${domainMap[locale]}/dp/${asin}?tag=${tagMap[locale]}`;
}
