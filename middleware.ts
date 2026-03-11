import createMiddleware from "next-intl/middleware";

export default createMiddleware({
  locales:         ["fr", "en", "de"],
  defaultLocale:   "fr",
  localePrefix:    "always",
  localeDetection: true, // detect Accept-Language on first visit → redirect to user's language
});

export const config = {
  matcher: [
    // Match all pathnames except for static files, _next, api
    "/((?!_next|api|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:png|jpg|jpeg|gif|svg|ico|css|js|woff2?)).*)",
  ],
};
