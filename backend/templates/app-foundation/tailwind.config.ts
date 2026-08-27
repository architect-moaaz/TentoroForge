import type { Config } from "tailwindcss";
// tailwindTokens converts @tentoroforge/library's flat token map into nested
// Tailwind theme objects so that Tailwind utility classes (e.g. text-primary-500,
// p-4) are generated from the same token values used by the schema renderer.
// NOTE: this import runs at build time (Next.js/PostCSS processes tailwind.config.ts
// via its own module system); the @tentoroforge/library dep is available after
// `npm install` in a generated app that includes the file: reference below.
import { tailwindTokens } from "./src/theme/tailwind-tokens";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  // Grid/library components compose some utility names dynamically
  // (`lg:grid-cols-${n}`), which the JIT scanner can never see —
  // without a safelist those classes render in the DOM with no CSS
  // rule and multi-column layouts silently collapse to the fallback.
  safelist: [
    { pattern: /^grid-cols-(1|2|3|4|5|6)$/, variants: ["sm", "md", "lg", "xl"] },
  ],
  theme: {
    extend: {
      // Merge token-derived values with the existing shadcn/radix CSS-var-based
      // colors so both systems are available in the same Tailwind build.
      colors: {
        ...tailwindTokens.colors,
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        // Status palette — emitted by design_agent into globals.css :root
        // (see _PALETTE_TO_CSS_VAR in backend/agents/design_agent.py).
        // Without these the LLM's `bg-success` / `text-warning` etc. silently
        // drop, making every generated app monochrome.
        success: {
          DEFAULT: "var(--color-success, hsl(142 71% 45%))",
          foreground: "var(--color-success-foreground, hsl(0 0% 100%))",
        },
        warning: {
          DEFAULT: "var(--color-warning, hsl(38 92% 50%))",
          foreground: "var(--color-warning-foreground, hsl(0 0% 100%))",
        },
        info: {
          DEFAULT: "var(--color-info, hsl(217 91% 60%))",
          foreground: "var(--color-info-foreground, hsl(0 0% 100%))",
        },
      },
      spacing: tailwindTokens.spacing,
      fontSize: tailwindTokens.fontSize,
      borderRadius: {
        ...tailwindTokens.borderRadius,
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      boxShadow: tailwindTokens.boxShadow,
    },
  },
  plugins: [],
};

export default config;
