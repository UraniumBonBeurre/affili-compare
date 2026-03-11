import { redirect } from "next/navigation";

// Redirige la racine "/" vers "/fr" (locale par défaut)
export default function RootPage() {
  redirect("/fr");
}
