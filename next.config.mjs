import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

const nextConfig = {
  // next build uses .next/types/** constraints that conflict with Supabase's
  // typed client inference; tsc --noEmit (CI) validates types separately.
  typescript: { ignoreBuildErrors: true },
  // @xenova/transformers contient des fichiers WASM et binaires :
  // il faut l'externaliser pour que webpack ne tente pas de le bundler.
  experimental: {
    serverComponentsExternalPackages: ["@xenova/transformers"],
  },
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "pub-*.r2.dev" },
      { protocol: "https", hostname: "*.supabase.co" },
      { protocol: "https", hostname: "m.media-amazon.com" },
      { protocol: "https", hostname: "images-na.ssl-images-amazon.com" },
      // Awin / ProductServe (images des flux produits)
      { protocol: "https", hostname: "images2.productserve.com" },
      { protocol: "https", hostname: "productserve.com" },
      { protocol: "https", hostname: "*.productserve.com" },
      // Images marchands Awin (URLs directes depuis les flux)
      { protocol: "https", hostname: "media.rueducommerce.fr" },
      { protocol: "https", hostname: "*.rueducommerce.fr" },
    ],
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default withNextIntl(nextConfig);
