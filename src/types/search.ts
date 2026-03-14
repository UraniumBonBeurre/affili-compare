/**
 * Types partagés pour la recherche LLM — utilisés par l'API route ET les composants client.
 */

export interface SearchAffiliateLink {
  id: string;
  partner: string;
  price: number | null;
  currency: string;
  url: string;
  in_stock: boolean;
}

export interface SearchResultItem {
  id: string;
  name: string;
  brand: string | null;
  image_url: string | null;
  links: SearchAffiliateLink[];
  comparison_slug?: string | null;
  category_slug?: string | null;
  /** Explication générée par le LLM */
  explanation?: string;
}

/** Article de sélection renvoyé dans les résultats de recherche */
export interface ArticleMatch {
  slug: string;
  title: string;
  subcategory: string;
  pinImages: string[];
}

export interface SearchApiResponse {
  results: SearchResultItem[];
  articles?: ArticleMatch[];
  fromLLM: boolean;
  message?: string;
  /** Tri automatique détecté par le LLM selon l'intention prix de la requête */
  autoSort?: "price_asc" | "price_desc" | "relevance";
}
