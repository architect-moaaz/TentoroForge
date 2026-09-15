import type { Config } from "tailwindcss";
// tailwindTokens converts @tentoroforge/library's flat token map into nested
// Tailwind theme objects so that Tailwind utility classes (e.g. text-primary-500,
// p-4) are generated from the same token values used by the schema renderer.
// NOTE: this import runs at build time (Next.js/PostCSS processes tailwind.config.ts
// via its own module system); the @tentoroforge/library dep is available after
// `npm install` in a generated app that includes the file: reference below.
import { tailwindTokens } from "./src/theme/tailwind-tokens";

const config: Config = {
  // PAGE SCHEMAS ARE SOURCE FOR TAILWIND, for the same reason the safelist
  // below exists: JIT compiles only what it can SEE by scanning, and a
  // class it never sees renders in the DOM with no rule behind it.
  //
  // A Figma-derived page carries its design in `className` — 398 distinct
  // classes on one real dashboard, 376 of them arbitrary values such as
  // `bg-[#ededed]`, `gap-[16px]`, `font-['Clash_Display:Medium']`. Those
  // live in `src/schemas/*.json`, read at runtime, so scanning JS/TS alone
  // missed every one: the fidelity survived extraction, composition, the
  // contract and the projection, and was lost here.
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/schemas/**/*.json",
  ],
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
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
          subtle: "hsl(var(--destructive-subtle, 0 86% 97%))",
          "subtle-foreground": "hsl(var(--destructive-subtle-foreground, 0 74% 32%))",
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        // Status palette. The single source is the token contract
        // (packages/library/src/theme/token-contract.json): the blueprint
        // projector fills `--success` / `--success-subtle` / … from
        // designSystem, so `bg-success` / `bg-success-subtle` reach the app's
        // real palette. The legacy `generate.py` path fills `--color-success`
        // instead (design_agent), so it is kept as a fallback; the bare hsl
        // triplet is the last resort so a status class never silently drops.
        // Each status carries the locked 4-token shape (solid + foreground +
        // subtle + subtle-foreground) so a Badge tint and a solid fill both
        // resolve to the design's colour.
        success: {
          DEFAULT: "hsl(var(--success, var(--color-success, 142 71% 45%)))",
          foreground: "hsl(var(--success-foreground, var(--color-success-foreground, 0 0% 100%)))",
          subtle: "hsl(var(--success-subtle, 141 79% 93%))",
          "subtle-foreground": "hsl(var(--success-subtle-foreground, 142 71% 22%))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning, var(--color-warning, 38 92% 50%)))",
          foreground: "hsl(var(--warning-foreground, var(--color-warning-foreground, 0 0% 100%)))",
          subtle: "hsl(var(--warning-subtle, 48 96% 89%))",
          "subtle-foreground": "hsl(var(--warning-subtle-foreground, 31 92% 30%))",
        },
        info: {
          DEFAULT: "hsl(var(--info, var(--color-info, 217 91% 60%)))",
          foreground: "hsl(var(--info-foreground, var(--color-info-foreground, 0 0% 100%)))",
          subtle: "hsl(var(--info-subtle, 204 94% 94%))",
          "subtle-foreground": "hsl(var(--info-subtle-foreground, 201 96% 26%))",
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
