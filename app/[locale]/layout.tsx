import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";
import { notFound } from "next/navigation";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { AffiliateDisclosure } from "@/components/AffiliateDisclosure";
import { ThemeProvider } from "@/components/ThemeProvider";
import type { Locale } from "@/types/database";
import "../globals.css";

// Inline script injected in <head> to apply saved theme BEFORE first paint (no flash)
const ANTI_FOIT = `try{var t=localStorage.getItem('theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');if(t==='dark')document.documentElement.classList.add('dark');}catch(e){}`;

const inter = Inter({ subsets: ["latin"] });

const locales: Locale[] = ["fr", "en", "de"];

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
      <head>
        <script dangerouslySetInnerHTML={{ __html: ANTI_FOIT }} />
      </head>
      <body className={`${inter.className} bg-[#F8F9FA] dark:bg-gray-950 text-gray-900 dark:text-gray-100 antialiased`}>
        <NextIntlClientProvider messages={messages}>
          <ThemeProvider>
            <AffiliateDisclosure />
            <Navbar locale={locale as Locale} />
            <main className="max-w-5xl mx-auto px-4 py-8 min-h-[70vh]">{children}</main>
            <Footer locale={locale as Locale} />
          </ThemeProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
