/**
 * lib/embedding.ts — Génération d'embeddings vectoriels pour les requêtes
 * =========================================================================
 *
 * Modèle   : Xenova/bge-m3  (1024 dims, multilingue, ~570 Mo)
 * Runtime  : Node.js (Transformers.js v2 = @xenova/transformers)
 * Coût     : 0 € — modèle téléchargé une fois, caché dans /tmp
 *
 * BGE-M3 : pas de préfixe — ni "query:" ni "passage:" (contrairement à E5)
 *
 * Thread-safety : l'instance `extractor` est un module-level singleton réutilisé
 * entre les requêtes Next.js (le runtime Node.js persiste entre les appels en dev).
 */

// @ts-ignore — le package fournit ses propres types
import { pipeline, env } from "@xenova/transformers";

// Modèle identique à generate-embeddings.py côté Python
const MODEL = "Xenova/bge-m3";

// Cache du pipeline entre les requêtes (Next.js dev garde le module en mémoire)
let _extractor: ReturnType<typeof pipeline> | null = null;

async function getExtractor() {
  if (!_extractor) {
    // Dossier de cache : /tmp (fonctionne en serverless + local dev)
    env.cacheDir = "/tmp/xenova-cache";
    env.allowRemoteModels = true;
    _extractor = pipeline("feature-extraction", MODEL, { quantized: true });
  }
  return _extractor as Promise<(text: string, options: object) => Promise<{ data: Float32Array }>>;
}

/**
 * Génère l'embedding d'une requête utilisateur.
 * BGE-M3 n'utilise pas de préfixe.
 *
 * @returns tableau de 1024 nombres (vecteur normalisé), ou null si échec
 */
export async function embedQuery(text: string): Promise<number[] | null> {
  try {
    const extractor = await getExtractor();
    const output    = await extractor(text.trim(), { pooling: "mean", normalize: true });
    return Array.from(output.data as Float32Array);
  } catch (err) {
    console.warn("[embedding] Impossible de générer l'embedding :", err instanceof Error ? err.message : err);
    return null;
  }
}
