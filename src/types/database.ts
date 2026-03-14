export type Json = string | number | boolean | null | { [key: string]: Json } | Json[];

export interface Database {
  public: {
    Tables: {
      categories: {
        Row: {
          id: string;
          slug: string;
          name_fr: string;
          name_en: string | null;
          name_de: string | null;
          meta_description_fr: string | null;
          meta_description_en: string | null;
          meta_description_de: string | null;
          pinterest_board_id: string | null;
          icon: string | null;
          is_active: boolean;
          display_order: number;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["categories"]["Row"], "id" | "created_at"> & { id?: string; created_at?: string };
        Update: Partial<Database["public"]["Tables"]["categories"]["Insert"]>;
      };
      comparisons: {
        Row: {
          id: string;
          slug: string;
          category_id: string | null;
          title_fr: string;
          title_en: string | null;
          title_de: string | null;
          intro_fr: string | null;
          intro_en: string | null;
          intro_de: string | null;
          buying_guide_fr: string | null;
          buying_guide_en: string | null;
          buying_guide_de: string | null;
          faq_fr: Json | null;
          faq_en: Json | null;
          faq_de: Json | null;
          last_updated: string;
          is_published: boolean;
          seo_score: number | null;
          monthly_views: number;
          subcategory: string | null;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["comparisons"]["Row"], "id" | "created_at" | "last_updated"> & { id?: string; created_at?: string; last_updated?: string };
        Update: Partial<Database["public"]["Tables"]["comparisons"]["Insert"]>;
      };
      products: {
        Row: {
          id: string;
          name: string;
          brand: string;
          image_url: string | null;
          release_date: string | null;
          created_at: string;
          external_id: string | null;
          category_slug: string | null;
          embedding: number[] | null;
          embedding_text: string | null;
          merchant_key: string | null;
          merchant_name: string | null;
          price: number | null;
          currency: string | null;
          in_stock: boolean | null;
          affiliate_url: string | null;
          merchant_category: string | null;
          active: boolean | null;
          last_price_update: string | null;
          description: string | null;
          llm_category:     string | null;
          llm_niche:        string | null;
          llm_product_type: string | null;
        };
        Insert: Omit<Database["public"]["Tables"]["products"]["Row"], "id" | "created_at"> & { id?: string; created_at?: string };
        Update: Partial<Database["public"]["Tables"]["products"]["Insert"]>;
      };
      comparison_products: {
        Row: {
          id: string;
          comparison_id: string;
          product_id: string;
          position: number;
        };
        Insert: Omit<Database["public"]["Tables"]["comparison_products"]["Row"], "id"> & { id?: string };
        Update: Partial<Database["public"]["Tables"]["comparison_products"]["Insert"]>;
      };
      affiliate_links: {
        Row: {
          id: string;
          product_id: string | null;
          comparison_id: string | null;
          partner: string;
          country: string;
          url: string;
          price: number | null;
          currency: string;
          in_stock: boolean;
          commission_rate: number | null;
          paapi_enabled: boolean | null;
          last_checked: string;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["affiliate_links"]["Row"], "id" | "created_at" | "last_checked"> & { id?: string; created_at?: string; last_checked?: string };
        Update: Partial<Database["public"]["Tables"]["affiliate_links"]["Insert"]>;
      };
      top_articles: {
        Row: {
          id: string;
          slug: string;
          url: string | null;
          title: string;
          content: Json | null;
          pin_images: Json | null;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["top_articles"]["Row"], "id" | "created_at"> & { id?: string; created_at?: string };
        Update: Partial<Database["public"]["Tables"]["top_articles"]["Insert"]>;
      };
      pinterest_pins: {
        Row: {
          id: string;
          comparison_id: string | null;
          pin_id: string | null;
          image_r2_key: string | null;
          image_url: string | null;
          title: string | null;
          description: string | null;
          locale: string;
          board_id: string | null;
          published_at: string | null;
          impressions: number;
          clicks: number;
          saves: number;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["pinterest_pins"]["Row"], "id" | "created_at"> & { id?: string; created_at?: string };
        Update: Partial<Database["public"]["Tables"]["pinterest_pins"]["Insert"]>;
      };
    };
    Functions: {
      search_products_hybrid: {
        Args: {
          query_embedding: number[];
          query_text?: string;
          match_count?: number;
          brand_filter?: string | null;
          category_filter?: string | null;
        };
        Returns: Array<{
          id: string;
          name: string;
          brand: string | null;
          image_url: string | null;
          category_slug: string | null;
          affiliate_url: string | null;
          price: number | null;
          currency: string | null;
          in_stock: boolean | null;
          merchant_key: string | null;
          hybrid_score: number;
          in_lexical: boolean;
        }>;
      };
    };
  };
}

// Handy derived types
export type Category       = Database["public"]["Tables"]["categories"]["Row"];
export type Comparison     = Database["public"]["Tables"]["comparisons"]["Row"];
export type Product        = Database["public"]["Tables"]["products"]["Row"];
export type AffiliateLink  = Database["public"]["Tables"]["affiliate_links"]["Row"];
export type PinterestPin   = Database["public"]["Tables"]["pinterest_pins"]["Row"];
export type TopArticle     = Database["public"]["Tables"]["top_articles"]["Row"];

export type FaqItem = { question: string; answer: string };

export type Locale = "fr" | "en";

/** Enriched product used in comparison pages */
export interface ProductWithLinks extends Product {
  links: AffiliateLink[];
}

/** Full comparison page data */
export interface ComparisonWithProducts extends Comparison {
  category: Category;
  products: ProductWithLinks[];
}
