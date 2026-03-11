/**
 * Arborescence du site — source de vérité unique.
 * Ajouter une catégorie ici suffit pour la faire apparaître partout.
 */

export interface SiteCategory {
  /** Slug URL (doit correspondre à la table categories en DB) */
  slug: string;
  nameFr: string;
  nameEn: string;
  /** Emoji affiché dans le graphe et les UI */
  icon: string;
  /** Couleur hex du nœud dans le star graph */
  color: string;
  /** Bref descriptif (meta / tooltip) */
  descriptionFr: string;
}

export const SITE_CATEGORIES: SiteCategory[] = [
  {
    slug:          "informatique",
    nameFr:        "Informatique",
    nameEn:        "Computers",
    icon:          "💻",
    color:         "#3B82F6",
    descriptionFr: "PC portables, SSD, claviers, écrans…",
  },
  {
    slug:          "gaming",
    nameFr:        "Gaming",
    nameEn:        "Gaming",
    icon:          "🎮",
    color:         "#8B5CF6",
    descriptionFr: "Fauteuils, casques, souris, tapis de jeu…",
  },
  {
    slug:          "tv-hifi",
    nameFr:        "TV & Hi-Fi",
    nameEn:        "TV & Hi-Fi",
    icon:          "📺",
    color:         "#F59E0B",
    descriptionFr: "Téléviseurs, enceintes, barres de son…",
  },
  {
    slug:          "smartphone",
    nameFr:        "Smartphone",
    nameEn:        "Smartphone",
    icon:          "📱",
    color:         "#10B981",
    descriptionFr: "Smartphones Android, iPhone, tablettes…",
  },
  {
    slug:          "electromenager",
    nameFr:        "Électroménager",
    nameEn:        "Appliances",
    icon:          "🔌",
    color:         "#6366F1",
    descriptionFr: "Lave-linge, réfrigérateurs, aspirateurs…",
  },
  {
    slug:          "cuisine",
    nameFr:        "Cuisine",
    nameEn:        "Kitchen",
    icon:          "🍳",
    color:         "#EF4444",
    descriptionFr: "Robots ménagers, cafetières, micro-ondes…",
  },
  {
    slug:          "maison",
    nameFr:        "Maison & Déco",
    nameEn:        "Home & Decor",
    icon:          "🏠",
    color:         "#F97316",
    descriptionFr: "Mobilier, luminaires, rangement…",
  },
  {
    slug:          "beaute",
    nameFr:        "Beauté & Santé",
    nameEn:        "Beauty & Health",
    icon:          "💄",
    color:         "#EC4899",
    descriptionFr: "Soins, maquillage, électro-beauté…",
  },
];
