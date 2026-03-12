import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        amazon:    "#FF9900",
        fnac:      "#E8990C",
        cdiscount: "#E4001B",
        darty:     "#E30C14",
        ebay:      "#E53238",
        brand: {
          50:  "#faf8f6",
          500: "#78716c",
          600: "#57534e",
          700: "#44403c",
        },
      },
      fontFamily: {
        sans: ["var(--font-dm-sans)", "system-ui", "sans-serif"],
        playfair: ["var(--font-playfair)", "Georgia", "serif"],
      },
      keyframes: {
        slideUp: {
          from: { transform: "translateY(100%)" },
          to:   { transform: "translateY(0)" },
        },
        slideDown: {
          from: { transform: "translateY(0)" },
          to:   { transform: "translateY(100%)" },
        },
        fadeIn: {
          from: { opacity: "0", transform: "translateY(12px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "slide-up":   "slideUp 440ms cubic-bezier(0.32, 0.72, 0, 1) forwards",
        "slide-down": "slideDown 380ms cubic-bezier(0.32, 0.72, 0, 1) forwards",
        "fade-in":    "fadeIn 300ms ease-out forwards",
      },
    },
  },
  plugins: [],
};

export default config;
