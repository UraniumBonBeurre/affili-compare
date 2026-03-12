/**
 * Tests unitaires pour lib/search-utils.ts
 *
 * T1    parseQuery — "tapis de souris" : "tapis" présent, "mouse" ABSENT
 * T2    parseQuery — "TV pas cher" : priceIntent=cheapest
 * T3    parseQuery — "TV Samsung haut de gamme" : priceIntent=premium
 * T4    parseQuery — "chaise gaming" : keywords pour chaises gaming
 * T5    parseQuery — "TV 4K" : expand 4k → "4k" ou "uhd"
 * T6    parseQuery — query vide : sqlKeywords vide
 * T7    parseQuery — "casque bluetooth" : pas de "mouse"
 * T8    parseQuery — rawQuery préservé
 * T8b   parseQuery — "chaise de bureau" → qualifier "bureau"
 * T8c   parseQuery — "chaise gaming" → qualifier "gaming"
 * T8d   parseQuery — "clavier mecanique sans fil" → qualifiers "mecanique" + "sans fil"
 * T8e   parseQuery — "TV pas cher" → aucun qualifier de type
 * T8f   parseQuery — "TV Asus" → brand = "asus"
 * T8g   parseQuery — "chaise gaming marque Samsung" → brand = "samsung"
 * T8h   parseQuery — "TV sous 300€" → maxPrice = 300
 * T8i   parseQuery — "TV haut de gamme plus de 1000€" → minPrice = 1000
 * T8j   parseQuery — sans budget → maxPrice null, minPrice null
 * T9-14 parseLlmJson — robustesse JSON
 * T15   extractBrand — marque dans un token simple
 * T16   extractMaxPrice / extractMinPrice
 */

import { describe, it, expect } from "vitest";
import { parseQuery, parseLlmJson, extractBrand, extractMaxPrice, extractMinPrice } from "../lib/search-utils";

// ─── parseQuery ───────────────────────────────────────────────────────────────

describe("parseQuery — synonymes & mots-clés SQL", () => {
  it("T1 — 'tapis de souris' : 'tapis' présent, 'mouse' ABSENT", () => {
    const { sqlKeywords } = parseQuery("tapis de souris");
    expect(sqlKeywords).toContain("tapis");
    // CRITIQUE : "mouse" ne doit PAS être dans les keywords SQL (causerait SpaceMouse à apparaître)
    expect(sqlKeywords).not.toContain("mouse");
  });

  it("T2 — 'TV pas cher' : priceIntent=cheapest, 'tv' dans keywords", () => {
    const { sqlKeywords, priceIntent } = parseQuery("TV pas cher");
    expect(priceIntent).toBe("cheapest");
    // Au moins 'tv' ou un synonyme
    const hasTV = sqlKeywords.some((k) => ["tv", "television", "ecran"].includes(k.toLowerCase()));
    expect(hasTV).toBe(true);
  });

  it("T3 — 'TV Samsung haut de gamme' : priceIntent=premium, 'samsung' dans keywords", () => {
    const { sqlKeywords, priceIntent } = parseQuery("TV Samsung haut de gamme");
    expect(priceIntent).toBe("premium");
    const hasSamsung = sqlKeywords.some((k) => k.toLowerCase() === "samsung");
    expect(hasSamsung).toBe(true);
  });

  it("T4 — 'chaise gaming' : keywords contiennent un terme lié aux chaises gamer (ergo/destrier/rgo)", () => {
    const { sqlKeywords } = parseQuery("chaise gaming");
    const hasChairTerm = sqlKeywords.some((k) =>
      ["ergo", "destrier", "rgo", "fauteuil", "siege", "chaise", "ergonomique"].includes(k.toLowerCase())
    );
    expect(hasChairTerm).toBe(true);
  });

  it("T5 — 'TV 4K' : keywords contiennent '4k' ou 'uhd'", () => {
    const { sqlKeywords } = parseQuery("TV 4K");
    const has4K = sqlKeywords.some((k) => ["4k", "uhd", "2160"].includes(k.toLowerCase()));
    expect(has4K).toBe(true);
  });

  it("T6 — query vide : sqlKeywords vide", () => {
    const { sqlKeywords } = parseQuery("");
    expect(sqlKeywords).toHaveLength(0);
  });

  it("T7 — 'casque bluetooth' : 'casque' présent, 'mouse' ABSENT", () => {
    const { sqlKeywords } = parseQuery("casque bluetooth");
    expect(sqlKeywords).not.toContain("mouse");
    const hasCasque = sqlKeywords.some((k) => ["casque", "headset", "headphone"].includes(k.toLowerCase()));
    expect(hasCasque).toBe(true);
  });

  it("T8 — rawQuery préserve la requête originale (pour le LLM)", () => {
    const { rawQuery } = parseQuery("TV vraiment pas cher");
    expect(rawQuery).toBe("TV vraiment pas cher");
  });

  it("T8b — 'chaise de bureau' : qualifier 'bureau' extrait, 'gaming' absent des qualifiers", () => {
    const { qualifiers } = parseQuery("chaise de bureau");
    expect(qualifiers).toContain("bureau");
    expect(qualifiers).not.toContain("gaming");
  });

  it("T8c — 'chaise gaming' : qualifier 'gaming' extrait", () => {
    const { qualifiers } = parseQuery("chaise gaming");
    expect(qualifiers).toContain("gaming");
  });

  it("T8d — 'clavier mecanique sans fil' : qualifiers contiennent 'mecanique' et 'sans fil'", () => {
    const { qualifiers } = parseQuery("clavier mecanique sans fil");
    expect(qualifiers).toContain("mecanique");
    expect(qualifiers).toContain("sans fil");
  });

  it("T8e — 'TV pas cher' : aucun qualifier de type (pas/cher ne sont pas des qualifiers)", () => {
    const { qualifiers } = parseQuery("TV pas cher");
    expect(qualifiers).toHaveLength(0);
  });

  it("T8f — 'TV Asus' : brand = 'asus'", () => {
    const { brand } = parseQuery("TV Asus");
    expect(brand).toBe("asus");
  });

  it("T8g — 'chaise gaming marque Samsung' : brand = 'samsung'", () => {
    const { brand } = parseQuery("chaise gaming marque Samsung");
    expect(brand).toBe("samsung");
  });

  it("T8h — 'TV sous 300€' : maxPrice = 300", () => {
    const { maxPrice } = parseQuery("TV sous 300€");
    expect(maxPrice).toBe(300);
  });

  it("T8i — 'TV haut de gamme plus de 1000€' : minPrice = 1000", () => {
    const { minPrice } = parseQuery("TV haut de gamme plus de 1000€");
    expect(minPrice).toBe(1000);
  });

  it("T8j — 'chaise gaming' : maxPrice null, minPrice null", () => {
    const { maxPrice, minPrice } = parseQuery("chaise gaming");
    expect(maxPrice).toBeNull();
    expect(minPrice).toBeNull();
  });
});

// ─── extractBrand ─────────────────────────────────────────────────────────────

describe("extractBrand", () => {
  it("T15a — marque simple dans un token : 'asus'", () => {
    expect(extractBrand("chaise gaming Asus")).toBe("asus");
  });

  it("T15b — pattern explicite 'marque X'", () => {
    expect(extractBrand("clavier marque Logitech")).toBe("logitech");
  });

  it("T15c — aucune marque connue → null", () => {
    expect(extractBrand("tapis de souris ergonomique")).toBeNull();
  });

  it("T15d — marque dans le pattern 'de chez X'", () => {
    expect(extractBrand("casque de chez Bose")).toBe("bose");
  });
});

// ─── extractMaxPrice / extractMinPrice ────────────────────────────────────────

describe("extractMaxPrice / extractMinPrice", () => {
  it("T16a — 'moins de 300€' → maxPrice 300", () => {
    expect(extractMaxPrice("TV moins de 300€")).toBe(300);
  });

  it("T16b — 'sous 500€' → maxPrice 500", () => {
    expect(extractMaxPrice("casque sous 500€")).toBe(500);
  });

  it("T16c — 'max 400' → maxPrice 400", () => {
    expect(extractMaxPrice("TV max 400")).toBe(400);
  });

  it("T16d — 'plus de 200€' → minPrice 200", () => {
    expect(extractMinPrice("casque plus de 200€")).toBe(200);
  });

  it("T16e — pas de budget → null", () => {
    expect(extractMaxPrice("chaise gaming razer")).toBeNull();
    expect(extractMinPrice("chaise gaming razer")).toBeNull();
  });
});

// ─── parseLlmJson ─────────────────────────────────────────────────────────────

describe("parseLlmJson — robustesse du parsing JSON LLM", () => {
  it("T9 — JSON valide : retourne ranked + auto_sort", () => {
    const result = parseLlmJson('{"ranked":[1,3,2],"auto_sort":"price_asc"}');
    expect(result).not.toBeNull();
    expect(result!.ranked).toEqual([1, 3, 2]);
    expect(result!.auto_sort).toBe("price_asc");
  });

  it("T10 — JSON entouré de texte (thinking model) : extrait correctement", () => {
    const raw = `Je vais analyser les produits...
Voici mon analyse.
{"ranked":[2,1,3],"auto_sort":"relevance"}
Voilà ma réponse.`;
    const result = parseLlmJson(raw);
    expect(result).not.toBeNull();
    expect(result!.ranked).toEqual([2, 1, 3]);
  });

  it("T11 — JSON avec backticks markdown : extrait correctement", () => {
    const raw = "```json\n{\"ranked\":[1,2],\"auto_sort\":\"price_desc\"}\n```";
    const result = parseLlmJson(raw);
    expect(result).not.toBeNull();
    expect(result!.ranked).toEqual([1, 2]);
  });

  it("T12 — tableau nu [1,2,3] : retourne {ranked:[1,2,3]}", () => {
    const result = parseLlmJson("[1,2,3]");
    expect(result).not.toBeNull();
    expect(result!.ranked).toEqual([1, 2, 3]);
  });

  it("T13 — texte totalement invalide : retourne null sans exception", () => {
    expect(() => parseLlmJson("blablabla rien ici")).not.toThrow();
    expect(parseLlmJson("blablabla rien ici")).toBeNull();
  });

  it("T14 — ranked vide : retourne {ranked:[]}", () => {
    const result = parseLlmJson('{"ranked":[],"auto_sort":"relevance"}');
    expect(result).not.toBeNull();
    expect(result!.ranked).toEqual([]);
  });
});
