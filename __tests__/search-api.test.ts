/**
 * Tests d'intégration — API POST /api/search (serveur sur http://localhost:3002)
 *
 * T15   — Requête vide → {results:[], fromLLM:false}
 * T16   — "TV" → résultats contenant des TV, fromLLM:true
 * T17   — "TV vraiment pas cher" → autoSort:"price_asc"
 * T18   — "tapis de souris" → aucun SpaceMouse/Mousetrapper
 * T19   — "chaise gaming" → résultats avec REKT/Destrier ou vide
 * T19b  — "chaise de bureau" → aucune chaise gaming dans les résultats
 * T20   — "TV Samsung haut de gamme" → Samsung en premier
 * T20b  — "TV Asus" → brand filter : brand field = "asus" dans parseQuery
 * T21   — corps JSON invalide → 400
 * T22   — LLM JSON malformé simulé → parseLlmJson retourne null (pas 502)
 * T23   — "TV sous 400€" → maxPrice filter : tous les résultats <= 400€
 * T23b  — "TV moins de 300 euros" → maxPrice extrait = 300
 * T23c  — brand + price combo : "casque Razer sous 200€" → brand=razer, maxPrice=200
 * T24   — locale "en" → réponse en anglais possible (fromLLM ou SQL fallback)
 */

import { describe, it, expect } from "vitest";
import { parseLlmJson, parseQuery } from "../lib/search-utils";

const BASE = "http://localhost:3002";

async function search(query: string, locale = "fr") {
  const res = await fetch(`${BASE}/api/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, locale }),
  });
  return { status: res.status, data: await res.json() };
}

describe("API /api/search — intégration live (nécessite serveur sur :3002)", () => {
  it("T15 — requête vide → results:[], fromLLM:false", async () => {
    const { status, data } = await search("  ");
    expect(status).toBe(200);
    expect(data.results).toEqual([]);
    expect(data.fromLLM).toBe(false);
  }, 10_000);

  it("T16 — 'TV' → résultats avec TVs, fromLLM:true", async () => {
    const { status, data } = await search("TV");
    expect(status).toBe(200);
    expect(data.results.length).toBeGreaterThan(0);
    expect(data.fromLLM).toBe(true);
    const hasTv = data.results.some((r: { name: string; brand: string }) =>
      /LG|Samsung|Philips|TCL|OLED|QLED|TV/i.test(r.name + r.brand)
    );
    expect(hasTv).toBe(true);
  }, 20_000);

  it("T17 — 'TV vraiment pas cher' → autoSort:price_asc, premier résultat le moins cher", async () => {
    const { status, data } = await search("TV vraiment pas cher");
    expect(status).toBe(200);
    expect(data.autoSort).toBe("price_asc");
    expect(data.results.length).toBeGreaterThan(0);
    const prices = data.results
      .map((r: { links: { price: number | null }[] }) => {
        const ps = r.links.map((l: { price: number | null }) => l.price).filter((p: number | null) => p != null);
        return ps.length ? Math.min(...(ps as number[])) : Infinity;
      });
    for (let i = 1; i < prices.length; i++) {
      expect(prices[i]).toBeGreaterThanOrEqual(prices[i - 1]);
    }
  }, 20_000);

  it("T18 — 'tapis de souris' → aucun SpaceMouse/Mousetrapper dans les résultats", async () => {
    const { status, data } = await search("tapis de souris");
    expect(status).toBe(200);
    const hasIrrelevant = data.results.some((r: { name: string }) =>
      /SpaceMouse|Mousetrapper|RollerMouse/i.test(r.name)
    );
    expect(hasIrrelevant).toBe(false);
  }, 20_000);

  it("T19 — 'chaise gaming' → résultats vides ou contenant Destrier/REKT", async () => {
    const { status, data } = await search("chaise gaming");
    expect(status).toBe(200);
    if (data.results.length > 0) {
      const hasChair = data.results.some((r: { name: string; brand: string }) =>
        /Destrier|REKT|RGo|ergo/i.test(r.name + r.brand)
      );
      expect(hasChair).toBe(true);
    } else {
      expect(data.results).toEqual([]);
    }
  }, 20_000);

  it("T19b — 'chaise de bureau' → résultats vides (gaming chairs ≠ office chairs)", async () => {
    const { status, data } = await search("chaise de bureau");
    expect(status).toBe(200);
    const hasGamingChair = data.results.some((r: { name: string; brand: string }) =>
      /gaming|ROG|Destrier|REKT|RGo/i.test(r.name + r.brand)
    );
    expect(hasGamingChair).toBe(false);
  }, 20_000);

  it("T20 — 'TV Samsung haut de gamme' → Samsung en premier résultat", async () => {
    const { status, data } = await search("TV Samsung haut de gamme");
    expect(status).toBe(200);
    expect(data.results.length).toBeGreaterThan(0);
    expect(data.results[0].brand).toMatch(/Samsung/i);
  }, 20_000);

  it("T20b — parseQuery 'TV Asus' → brand = 'asus' (extraction marque)", () => {
    // Test unitaire inline : vérifie que le champ brand remonte bien dans parseQuery
    const { brand } = parseQuery("TV Asus");
    expect(brand).toBe("asus");
  });

  it("T21 — corps JSON invalide → 400", async () => {
    const res = await fetch(`${BASE}/api/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "not json at all {{{",
    });
    expect(res.status).toBe(400);
  }, 10_000);

  it("T22 — LLM JSON malformé simulé → parseLlmJson retourne null, pas de 502", () => {
    const result = parseLlmJson("Je ne sais pas quoi répondre... voici mes pensées: undefined null {}");
    expect(result).toBeNull();
  });

  it("T23 — 'TV sous 400€' : maxPrice=400 extrait depuis parseQuery", () => {
    const { maxPrice } = parseQuery("TV sous 400€");
    expect(maxPrice).toBe(400);
  });

  it("T23b — 'TV moins de 300 euros' : maxPrice=300", () => {
    const { maxPrice } = parseQuery("TV moins de 300 euros");
    expect(maxPrice).toBe(300);
  });

  it("T23c — 'casque Razer sous 200€' : brand=razer + maxPrice=200", () => {
    const { brand, maxPrice } = parseQuery("casque Razer sous 200€");
    expect(brand).toBe("razer");
    expect(maxPrice).toBe(200);
  });

  it("T24 — locale 'en' → réponse HTTP 200 (pas de crash)", async () => {
    const { status, data } = await search("headset gaming", "en");
    expect(status).toBe(200);
    expect(Array.isArray(data.results)).toBe(true);
  }, 20_000);
});

describe("API /api/search — intégration live (nécessite serveur sur :3002)", () => {
  it("T15 — requête vide → results:[], fromLLM:false", async () => {
    const { status, data } = await search("  ");
    expect(status).toBe(200);
    expect(data.results).toEqual([]);
    expect(data.fromLLM).toBe(false);
  }, 10_000);

  it("T16 — 'TV' → résultats avec TVs, fromLLM:true", async () => {
    const { status, data } = await search("TV");
    expect(status).toBe(200);
    expect(data.results.length).toBeGreaterThan(0);
    expect(data.fromLLM).toBe(true);
    // Au moins un résultat contient "OLED", "QLED", "TV" ou une marque TV connue
    const hasTv = data.results.some((r: { name: string; brand: string }) =>
      /LG|Samsung|Philips|TCL|OLED|QLED|TV/i.test(r.name + r.brand)
    );
    expect(hasTv).toBe(true);
  }, 20_000);

  it("T17 — 'TV vraiment pas cher' → autoSort:price_asc, premier résultat le moins cher", async () => {
    const { status, data } = await search("TV vraiment pas cher");
    expect(status).toBe(200);
    expect(data.autoSort).toBe("price_asc");
    expect(data.results.length).toBeGreaterThan(0);
    // Vérifier que les prix sont croissants ou égaux
    const prices = data.results
      .map((r: { links: { price: number | null }[] }) => {
        const ps = r.links.map((l: { price: number | null }) => l.price).filter((p: number | null) => p != null);
        return ps.length ? Math.min(...(ps as number[])) : Infinity;
      });
    for (let i = 1; i < prices.length; i++) {
      expect(prices[i]).toBeGreaterThanOrEqual(prices[i - 1]);
    }
  }, 20_000);

  it("T18 — 'tapis de souris' → aucun SpaceMouse/Mousetrapper dans les résultats", async () => {
    const { status, data } = await search("tapis de souris");
    expect(status).toBe(200);
    // Soit 0 résultats (correct — pas de tapis en DB)
    // Soit résultats sans SpaceMouse/Mousetrapper/RollerMouse (le LLM filtre le hors-sujet)
    const hasIrrelevant = data.results.some((r: { name: string }) =>
      /SpaceMouse|Mousetrapper|RollerMouse/i.test(r.name)
    );
    expect(hasIrrelevant).toBe(false);
  }, 20_000);

  it("T19 — 'chaise gaming' → résultats vides ou contenant Destrier/REKT", async () => {
    const { status, data } = await search("chaise gaming");
    expect(status).toBe(200);
    // Acceptable : soit résultats avec chaises gaming, soit vide propre
    if (data.results.length > 0) {
      const hasChair = data.results.some((r: { name: string; brand: string }) =>
        /Destrier|REKT|RGo|ergo/i.test(r.name + r.brand)
      );
      expect(hasChair).toBe(true);
    } else {
      expect(data.results).toEqual([]);
    }
  }, 20_000);

  it("T19b — 'chaise de bureau' → résultats vides (gaming chairs ≠ office chairs)", async () => {
    const { status, data } = await search("chaise de bureau");
    expect(status).toBe(200);
    // Le LLM doit rejeter les chaises gaming quand l'utilisateur demande du bureau
    const hasGamingChair = data.results.some((r: { name: string; brand: string }) =>
      /gaming|ROG|Destrier|REKT|RGo/i.test(r.name + r.brand)
    );
    expect(hasGamingChair).toBe(false);
  }, 20_000);

  it("T20 — 'TV Samsung haut de gamme' → Samsung en premier résultat", async () => {
    const { status, data } = await search("TV Samsung haut de gamme");
    expect(status).toBe(200);
    expect(data.results.length).toBeGreaterThan(0);
    expect(data.results[0].brand).toMatch(/Samsung/i);
  }, 20_000);

  it("T21 — corps JSON invalide → 400", async () => {
    const res = await fetch(`${BASE}/api/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "not json at all {{{",
    });
    expect(res.status).toBe(400);
  }, 10_000);

  it("T22 — LLM JSON malformé simulé → parseLlmJson retourne null, pas de 502", () => {
    // Simuler directement : le LLM répond avec du texte incohérent
    const result = parseLlmJson("Je ne sais pas quoi répondre... voici mes pensées: undefined null {}");
    expect(result).toBeNull();
    // La route doit donc tomber dans le fallback → résultats bruts, pas d'erreur 502
    // (testé indirectement par T14 + ce test direct)
  });
});
