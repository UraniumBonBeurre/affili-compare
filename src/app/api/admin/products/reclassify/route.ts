import { NextRequest, NextResponse } from "next/server";
import { getSiteCategories, getNicheProductTypes } from "@/lib/site-categories";

export async function POST(req: NextRequest) {
  const { name, brand, description } = await req.json();

  const apiKey = process.env.GOOGLE_AI_API_KEY;
  if (!apiKey) return NextResponse.json({ error: "GOOGLE_AI_API_KEY manquante" }, { status: 500 });

  const cats = getSiteCategories();
  const npt  = getNicheProductTypes();

  // Build compact taxonomy for the prompt
  const taxoLines = cats.map(c => {
    const niches = c.niches.map(n => {
      const types = (npt[n.slug] ?? []).map(t => `${t.id}:${t.name_fr}`).join(", ");
      return `  ${n.slug} "${n.name}": ${types || "(aucun type)"}`;
    }).join("\n");
    return `${c.id} "${c.name}":\n${niches}`;
  }).join("\n");

  const productDesc = [name, brand, description?.slice(0, 400)].filter(Boolean).join(" — ");

  const prompt = `Tu es un expert en classification de produits e-commerce.
Produit : ${productDesc}

Classe ce produit dans la taxonomie ci-dessous.
Taxonomie (format: niche_slug "Nom": type_id:Nom type, ...):
${taxoLines}

Réponds en JSON uniquement, sans explication :
{"category":"category_id","niche":"niche_slug","product_type":"type_id"}`;

  const model = "gemini-3.1-flash-lite-preview";
  const gemRes = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{ role: "user", parts: [{ text: prompt }] }],
        generationConfig: {
          response_mime_type: "application/json",
          temperature: 0.1,
          max_output_tokens: 200,
        },
      }),
    }
  );

  if (!gemRes.ok) {
    const err = await gemRes.text();
    return NextResponse.json({ error: `Gemini error: ${err}` }, { status: 500 });
  }

  const gemData = await gemRes.json();
  const rawText = gemData.candidates?.[0]?.content?.parts?.[0]?.text;

  let result: { category: string; niche: string; product_type: string };
  try {
    result = JSON.parse(rawText);
  } catch {
    return NextResponse.json({ error: "Réponse Gemini invalide", raw: rawText }, { status: 500 });
  }

  // Enrich with human-readable labels
  const catObj   = cats.find(c => c.id === result.category);
  const nicheObj = cats.flatMap(c => c.niches).find(n => n.slug === result.niche);
  const typeObj  = (npt[result.niche] ?? []).find(t => t.id === result.product_type);

  return NextResponse.json({
    category:     { id: result.category,      name:    catObj?.name            ?? result.category },
    niche:        { slug: result.niche,        name:    nicheObj?.name          ?? result.niche },
    product_type: { id: result.product_type,   name_fr: typeObj?.name_fr        ?? result.product_type },
  });
}
