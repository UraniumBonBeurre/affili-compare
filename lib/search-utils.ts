/**
 * search-utils.ts — Logique pure d'analyse de requête de recherche.
 * Extraction depuis route.ts pour permettre les tests unitaires.
 */

// ─── Stopwords (mots vides — ne pas utiliser en SQL) ─────────────────────────
export const STOPWORDS = new Set([
  // FR
  "le","la","les","un","une","des","de","du","en","et","ou","à","au","aux",
  "par","sur","sous","pour","avec","je","tu","il","nous","vous","ils","me","te","se",
  "cherche","recherche","veux","besoin","avoir","trouver","tel","quel","quelle",
  "vrai","vraiment","vraie","genre","type","quelque","chose","aussi","alors","donc",
  "qui","que","quoi","dont","où","car","ni","si",
  // EN
  "the","a","an","for","with","looking","need","want","around","about","get","find","i","am","is",
  // DE
  "der","die","das","ein","eine","für","mit","unter","suche",
]);

// ─── Signaux d'intention prix ─────────────────────────────────────────────────
export const CHEAP_SIGNALS = [
  "pas cher","low cost","budget","abordable","economique","moins cher","bon marche",
  "petits prix","petit prix","pas tres cher","cheap","affordable","inexpensive",
  "gunstig","billig","preiswert","prix bas","peu cher","accessible","entree de gamme",
];

export const PREMIUM_SIGNALS = [
  "haut de gamme","premium","luxe","pro","professionnel","top",
  "high end","flagship","best","hochwertig","milieu de gamme",
];

/**
 * SYNONYMES : terme tapé (normalisé, sans accents, minuscules) → termes SQL à chercher.
 *
 * RÈGLE IMPORTANTE :
 *   - Ne jamais mettre un terme trop générique qui matcherait des produits hors sujet.
 *   - Ex : "souris" ne doit PAS mapper vers "mouse" (ILIKE %mouse% matcherait "SpaceMouse").
 *   - Préférer des termes spécifiques qui sont dans les noms de produits de la DB.
 */
export const SYNONYMS: Record<string, string[]> = {
  // ── Vidéo ──
  "tele":          ["TV","ecran","television"],
  "teles":         ["TV","television"],
  "television":    ["TV"],
  "televiseur":    ["TV"],
  "tv":            ["TV","television","ecran"],
  "4k":            ["4K","UHD","2160"],
  "uhd":           ["4K","UHD"],
  "oled":          ["OLED"],
  "qled":          ["QLED"],

  // ── Ordinateurs ──
  "pc":                    ["ordinateur","PC"],
  "laptop":                ["laptop","notebook","PC"],
  "ordi":                  ["ordinateur","PC"],
  "ordinateur":            ["ordinateur","PC","laptop"],
  // Bigrams : quand le bigram est reconnu, ses tokens individuels ne sont
  // PAS ajoutés séparément (cf. logique parseQuery ci-dessous).
  // Évite que "portable" seul matche les accessoires "pour PC portable".
  "ordinateur portable":   ["laptop","notebook"],
  "pc portable":           ["laptop","notebook"],
  "pc gamer":              ["gaming","PC","gamer"],
  "ordinateur de bureau":  ["desktop","ordinateur","PC"],
  "tapis de souris":       ["tapis","souris","mousepad"],
  "casque gaming":         ["casque","headset","gaming"],
  // Note : pas de "gaming" ici → évite que "chaise gaming" remonte les périphériques gaming.
  // Uniquement des termes propres au mobilier → FTS retourne vide si pas de chaises en base
  // → garde in_lexical déclenche len(results)=0.
  "chaise gaming":        ["destrier","noblechairs","secretlab","akracing","fauteuil","siege"],
  // Pas de "bureau" (matcherait supportS de bureau) ni "ergonomique" (claviers ergo).
  "chaise de bureau":     ["chaise","fauteuil","siege"],
  "clavier mecanique":     ["clavier","mecanique","keyboard"],
  "sans fil":              ["sans fil","wireless","bluetooth"],
  "barre de son":          ["barre","soundbar","enceinte"],
  "enceinte bluetooth":    ["enceinte","bluetooth","speaker"],
  "enceinte portable":     ["enceinte","portable","speaker"],
  "casque bluetooth":      ["casque","bluetooth","headphone"],
  "carte graphique":       ["GPU","graphique","RTX","RX"],
  "disque dur":            ["HDD","SSD","disque","stockage"],

  // ── Téléphones ──
  "phone":         ["smartphone","telephone"],
  "smartphone":    ["smartphone","telephone"],
  // "tel" est ambigu (téléphone vs "tel que") — ne pas ajouter

  // ── Souris : NE PAS mapper vers "mouse" (matcherait SpaceMouse/Mousetrapper) ──
  "souris":        ["souris","RollerMouse"],

  // ── Tapis de souris ──
  "tapis":         ["tapis"],

  // ── Claviers ──
  "clavier":       ["clavier","keyboard"],
  "keyboard":      ["clavier","keyboard"],

  // ── Casques audio ──
  "ecouteurs":     ["ecouteurs","earbuds","casque","intra"],
  "casque":        ["casque","headset"],
  "headset":       ["casque","headset"],

  // ── Enceintes ──
  "enceinte":      ["enceinte","speaker","barre"],

  // ── Manettes ──
  "manette":       ["manette","gamepad","controller"],

  // ── Stockage ──
  "ssd":           ["SSD","disque"],
  "disque":        ["SSD","HDD","disque","stockage"],

  // ── Tablettes ──
  "tablette":      ["tablette","tablet","ipad"],

  // ── Montres ──
  "montre":        ["montre","watch","smartwatch"],

  // ── Aspirateurs ──
  "aspirateur":    ["aspirateur","vacuum","robot"],

  // ── Électroménager ──
  "frigo":         ["refrigerateur","frigo","congelateur"],
  "imprimante":    ["imprimante","printer"],
  "camera":        ["camera","appareil","webcam"],
  "micro":         ["micro","microphone"],
  "routeur":       ["routeur","router","wifi","box"],

  // ── Chaises / Sièges gaming ──
  // Note : "ergo"/"ergonomique" intentionnellement absent ici pour éviter que
  // "chaise" seul ne remonte les claviers/souris ergonomiques.
  // Ces termes restent dans les bigrams "chaise gaming" et "chaise de bureau".
  "chaise":        ["chaise","fauteuil","siege"],
  "fauteuil":      ["fauteuil","chaise","siege"],
  "siege":         ["siege","fauteuil","chaise"],
  "gaming chair":  ["ergo","destrier","rgo","gaming"],
};

/**
 * Prix maximum explicite : patterns comme "moins de 300€", "sous 500€", "max 400€"
 * Retourne le prix numérique ou null.
 */
export function extractMaxPrice(query: string): number | null {
  const norm = query.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  // "moins de 300€", "sous 400€", "max 500", "jusqu'a 600", "budget 200"
  const m = norm.match(/(?:moins\s+de|sous|max(?:imum)?|jusqu['']?a|budget|maxi)\s*(\d{2,4})\s*[€e]?/i)
         ?? norm.match(/(\d{2,4})\s*[€e]\s*(?:max|maxi|maximum)?$/i);
  return m ? parseInt(m[1], 10) : null;
}

/**
 * Prix minimum explicite : patterns comme "plus de 300€", "min 200€"
 */
export function extractMinPrice(query: string): number | null {
  const norm = query.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const m = norm.match(/(?:plus\s+de|min(?:imum)?|au\s+moins|a\s+partir\s+de)\s*(\d{2,4})\s*[€e]?/i);
  return m ? parseInt(m[1], 10) : null;
}

/**
 * Marques connues (liste des marques présentes dans la DB + les plus courantes).
 * Toujours en minuscules, sans accents.
 * Mise à jour : ajouter ici les nouvelles marques au fur et à mesure.
 */
export const KNOWN_BRANDS = new Set([
  // TV / Audio
  "samsung","lg","sony","philips","tcl","hisense","panasonic","bose","jbl","yamaha","denon","harman",
  // PC / Gaming
  "asus","acer","lenovo","hp","dell","msi","razer","corsair","logitech","steelseries","hyperx",
  "alienware","gigabyte","zotac","nvidia","amd",
  // Smartphones
  "apple","iphone","google","pixel","xiaomi","oneplus","oppo","realme","huawei","motorola",
  // Chaises / Mobilier
  "rekt","noblechairs","secretlab","dxracer","ak racing","autonomous","ikea","haworth",
  // Casques / écouteurs
  "sennheiser","akg","beyerdynamic","jabra","plantronics","audio technica","skullcandy",
  // Stockage
  "samsung","seagate","western digital","wd","toshiba","kingston","crucial","sandisk",
  // Divers
  "anker","belkin","trust","nacon","thrustmaster","elgato","rode","blue",
]);

/**
 * Extrait la marque mentionnée dans une requête.
 * Retourne la marque telle que tapée, ou null.
 * Gère les patterns : "marque Asus", "Asus ROG", ou juste "Asus" dans la phrase.
 */
export function extractBrand(query: string): string | null {
  const norm = query.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");

  // Pattern explicite : "marque X", "de chez X"
  const explicitMatch = norm.match(/(?:marque|de\s+chez|brand)\s+([a-z][a-z0-9\s]{1,20}?)(?:\s+|$)/i);
  if (explicitMatch) {
    const candidate = explicitMatch[1].trim().split(/\s+/)[0]; // premier mot
    if (KNOWN_BRANDS.has(candidate)) return candidate;
  }

  // Recherche dans les tokens
  const tokens = norm.split(/\s+/);
  for (const token of tokens) {
    if (KNOWN_BRANDS.has(token)) return token;
  }

  // Bigrams (ex: "western digital", "ak racing")
  const words = norm.split(/\s+/);
  for (let i = 0; i < words.length - 1; i++) {
    const bigram = `${words[i]} ${words[i + 1]}`;
    if (KNOWN_BRANDS.has(bigram)) return bigram;
  }

  return null;
}

/**
 * Qualificateurs de type : mots qui précisent le SOUS-TYPE du produit.
 * Ce sont des contraintes strictes pour le LLM : "chaise de bureau" ≠ "chaise gaming".
 */
export const TYPE_QUALIFIERS = new Set([
  // Contexte d'usage
  "bureau","gaming","esport","portable","nomade","voyage","outdoor","professionnel","pro",
  // Connectivité
  "filaire","sans fil","wireless","bluetooth","wifi","usb","radio",
  // Propriétés physiques
  "mecanique","membrane","optique","laser","tactile","silencieux","silent","rgb",
  // Taille / format
  "compact","mini","xl","tkl","60%",
  // Utilisateur
  "enfant","adulte","massant","electrique","reglable",
]);

export interface ParsedQuery {
  /** Termes à utiliser dans le filtre SQL (OR ILIKE) */
  sqlKeywords: string[];
  /** Intention de prix détectée */
  priceIntent: "cheapest" | "premium" | null;
  /** Requête originale (pour le LLM) */
  rawQuery: string;
  /** Qualificateurs de sous-type extraits (contrainte stricte pour LLM) */
  qualifiers: string[];
  /** Marque détectée (pour filtre DB et vector search) */
  brand: string | null;
  /** Prix maximum extrait ("sous 300€", "max 500€") */
  maxPrice: number | null;
  /** Prix minimum extrait */
  minPrice: number | null;
}

/**
 * Analyse sémantique une requête utilisateur :
 *   - Expansion via synonymes
 *   - Détection d'intention prix
 *   - Nettoyage des stopwords
 */
export function parseQuery(query: string): ParsedQuery {
  const norm = query
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\w\s€$]/g, " ");

  // Détection intention prix (sur la phrase complète)
  let priceIntent: "cheapest" | "premium" | null = null;
  if (CHEAP_SIGNALS.some((s) => norm.includes(s))) priceIntent = "cheapest";
  else if (PREMIUM_SIGNALS.some((s) => norm.includes(s))) priceIntent = "premium";

  // Tokens par mots individuels
  const tokens = norm
    .split(/\s+/)
    // Exclure les purs nombres et les prix "500€" "300$" pour éviter
    // que "TV sous 500€" trouve "JBL TUNE 500" via FTS.
    .filter((w) => w.length >= 2 && !STOPWORDS.has(w) && !/^\d+[€$]?$/.test(w));

  // Vérifier aussi les n-grammes bi-mots pour les synonymes composés
  const words = norm.split(/\s+/);
  const bigrams = words.slice(0, -1).map((w, i) => `${w} ${words[i + 1]}`);

  const expanded = new Set<string>();
  // Traiter les bigrams EN PREMIER pour marquer leurs tokens comme "consommés".
  // Exemple : "ordinateur portable" → bigram match → "ordinateur" et "portable"
  //           ne sont PAS ajoutés individuellement → évite les faux positifs FTS
  //           ("station d'accueil pour PC portable" ne remonte plus pour "ordinateur portable").
  const consumedByBigram = new Set<string>();
  for (const bg of bigrams) {
    if (SYNONYMS[bg]) {
      SYNONYMS[bg].forEach((s) => expanded.add(s.toLowerCase()));
      bg.split(" ").forEach((w) => consumedByBigram.add(w));
    }
  }
  for (const t of tokens) {
    if (consumedByBigram.has(t)) continue; // consommé par un bigram
    if (SYNONYMS[t]) {
      SYNONYMS[t].forEach((s) => expanded.add(s.toLowerCase()));
    } else {
      // Token sans synonyme → ajout direct
      expanded.add(t);
    }
  }

  // Fallback : si vide, essayer avec tous les mots >= 2 chars
  if (expanded.size === 0) {
    norm.split(/\s+/).filter((w) => w.length >= 2).forEach((w) => expanded.add(w));
  }

  // Extraire les qualificateurs de type (contraintes strictes pour le LLM)
  const qualifiers = tokens.filter((t) => TYPE_QUALIFIERS.has(t));
  // Vérifier aussi les bigrams (ex: "sans fil")
  const bgQualifiers = bigrams.filter((bg) => TYPE_QUALIFIERS.has(bg));
  const allQualifiers = [...new Set([...qualifiers, ...bgQualifiers])];

  return { sqlKeywords: [...expanded], priceIntent, rawQuery: query, qualifiers: allQualifiers, brand: extractBrand(query), maxPrice: extractMaxPrice(query), minPrice: extractMinPrice(query) };
}

/**
 * Parse la réponse JSON du LLM, avec plusieurs stratégies de secours.
 * Ne lève jamais d'exception — retourne null si parsing impossible.
 */
export function parseLlmJson(raw: string): { ranked: number[]; auto_sort?: string } | null {
  const clean = raw.trim().replace(/^```(?:json)?\n?|\n?```$/g, "");

  // Essai 1 : JSON direct
  try {
    const parsed = JSON.parse(clean);
    if (Array.isArray(parsed?.ranked)) return parsed;
  } catch { /* continue */ }

  // Essai 2 : extraire le premier objet JSON dans le texte
  const objMatch = clean.match(/\{[\s\S]*?\}/);
  if (objMatch) {
    try {
      const parsed = JSON.parse(objMatch[0]);
      if (Array.isArray(parsed?.ranked)) return parsed;
    } catch { /* continue */ }
  }

  // Essai 3 : extraire un tableau d'indices
  const arrMatch = clean.match(/\[[\d,\s]+\]/);
  if (arrMatch) {
    try {
      const ranked = JSON.parse(arrMatch[0]);
      if (Array.isArray(ranked)) return { ranked };
    } catch { /* continue */ }
  }

  return null;
}
