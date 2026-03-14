/**
 * slugify.ts — Convert display strings to URL-safe slugs and vice-versa.
 */

export function slugify(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")   // strip accents
    .replace(/[^a-z0-9]+/g, "-")       // non-alphanumeric → hyphen
    .replace(/(^-|-$)/g, "");           // trim leading/trailing hyphens
}

/** Capitalize first letter of each word, replace hyphens with spaces. */
export function unslugify(s: string): string {
  return s
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
