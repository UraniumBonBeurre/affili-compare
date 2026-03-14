import type { Metadata } from "next";
import { DM_Sans, Playfair_Display } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";
import { notFound } from "next/navigation";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import type { Locale } from "@/types/database";
import "../globals.css";

const dmSans = DM_Sans({ subsets: ["latin"], variable: "--font-dm-sans" });
const playfair = Playfair_Display({ subsets: ["latin"], variable: "--font-playfair" });

const locales: Locale[] = ["fr", "en"];

// next-intl reads request headers; mark the entire locale tree as dynamic
// so Vercel doesn't try (and fail) to pre-render during build.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: { default: "MyGoodPick — Comparez avant d'acheter", template: "%s | MyGoodPick" },
  description: "Comparatifs produits indépendants avec prix en temps réel et liens affiliés multi-partenaires.",
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://mygoodpick.com"),
};

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { locale: string };
}) {
  const { locale } = params;
  if (!locales.includes(locale as Locale)) notFound();

  const messages = await getMessages();

  return (
    <html lang={locale} suppressHydrationWarning>
      <body className={`${dmSans.variable} ${playfair.variable} font-sans text-stone-800 antialiased min-h-screen relative`}>
        {/* Background image — very light blur, mostly visible */}
        <div
          className="fixed inset-0 -z-20 bg-cover bg-center"
          style={{
            backgroundImage: "url('/bg-interior.jpg')",
            filter: "blur(2px) brightness(0.96)",
            transform: "scale(1.01)",
          }}
        />
        {/* Very subtle warm overlay */}
        <div className="fixed inset-0 -z-10 bg-white/15" />

        <NextIntlClientProvider messages={messages}>
          <Navbar locale={locale as Locale} />
          <main className="max-w-6xl mx-auto px-4">
            {children}
          </main>
          <Footer locale={locale as Locale} />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
