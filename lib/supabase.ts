import { createClient } from "@supabase/supabase-js";
import type { Database } from "@/types/database";

const supabaseUrl  = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

// Client public (anon key) — utilisé dans les Server Components
export const supabase = createClient<Database>(supabaseUrl, supabaseAnon);

// Factory pour Server Components qui ont besoin d'un client frais par requête
export function createSupabaseServerClient() {
  return createClient<Database>(supabaseUrl, supabaseAnon);
}

/**
 * Service role client — ⚠ uniquement côté serveur (API routes, Server Actions)
 * Ne jamais exposer SUPABASE_SERVICE_ROLE_KEY côté client.
 */
export function createServiceClient() {
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!serviceKey) {
    throw new Error("SUPABASE_SERVICE_ROLE_KEY is not set");
  }
  return createClient<Database>(supabaseUrl, serviceKey, {
    auth: { persistSession: false },
  });
}
