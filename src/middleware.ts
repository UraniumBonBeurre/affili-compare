import createMiddleware from "next-intl/middleware";

export default createMiddleware({
  locales:         ["fr", "en"],
  defaultLocale:   "fr",
  localePrefix:    "always",
  localeDetection: false, // désactivé : on ne redirige pas automatiquement selon Accept-Language
});

export const config = {
  matcher: [
    // Match all pathnames except for static files, _next, api
    "/((?!_next|api|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:png|jpg|jpeg|gif|svg|ico|css|js|woff2?)).*)",
  ],
};
