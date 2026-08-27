import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  // Tailwind's JIT only emits CSS for classes it sees in the `content` paths.
  // The schema-driven runtime renders components from `@tentoroforge/library`
  // (and primitives from `@tentoroforge/renderer`) — their Tailwind utility
  // classes live in `packages/library/src/**` and `packages/renderer/src/**`,
  // not in the scaffold itself. Without these globs, every generated page
  // renders with class attributes that don't resolve to compiled CSS — that's
  // the root cause of every "looks unstyled" symptom observed in the scaffold.
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
    "../../packages/library/src/**/*.{js,ts,jsx,tsx}",
    "../../packages/renderer/src/**/*.{js,ts,jsx,tsx}",
    // Schema-driven runtime: per-project JSON schemas carry Tailwind classes
    // (especially arbitrary values from the Figma MCP pipeline like
    // `grid-cols-[repeat(2,minmax(0,1fr))]` or `bg-[#841013]`). Without these
    // globs, JIT skips those tokens and the page renders without the layout
    // / color classes derived from the design.
    //
    // Narrowed to the two directories where classes actually live so
    // Tailwind doesn't scan every output app's node_modules (a `**/*.json`
    // glob emitted the "matching all of node_modules" warning and made
    // first-compile take 60+ seconds on a workstation with hundreds of
    // apps under output/).
    "../../output/*/src/schemas/**/*.json",
    "../../output/*/src/contracts/**/*.json",
    "../../output/*/contracts/**/*.json",
  ],
  theme: {
    extend: {
      colors: {
        border: "var(--border)",
        input: "var(--input)",
        ring: "var(--ring)",
        background: "var(--background)",
        foreground: "var(--foreground)",
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },
        // Status colours — emitted by design_agent into globals.css :root.
        // Without these entries Tailwind silently drops `bg-success` /
        // `text-warning` etc., which is why description-generated apps
        // looked monochrome (only --primary / --muted / --foreground were
        // ever resolvable).
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
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      // ── Type scale (Tier S of the design-system polish) ─────────────
      // Named scale that every library component references instead of
      // picking ad-hoc `text-lg` / `text-xl` / `text-2xl`. Defining named
      // tokens here means a single edit to this file shifts the platform's
      // entire typography rhythm, and it makes "page-title > section >
      // card-title > body > caption > micro" explicit in code rather than
      // an inferred convention.
      //
      // The numeric pairs are [font-size, { lineHeight, letterSpacing,
      // fontWeight }]. Defaults chosen to match Linear's compact rhythm —
      // each step ~1.25× the previous, semantic-bold weights for headings,
      // regular weight for body / caption.
      fontSize: {
        "page-title":    ["1.875rem",  { lineHeight: "2.25rem",  letterSpacing: "-0.02em", fontWeight: "700" }], // 30px
        "section-title": ["1.25rem",   { lineHeight: "1.75rem",  letterSpacing: "-0.01em", fontWeight: "600" }], // 20px
        "card-title":    ["1rem",      { lineHeight: "1.5rem",                              fontWeight: "600" }], // 16px
        "body":          ["0.875rem",  { lineHeight: "1.375rem"                                              }], // 14px
        "caption":       ["0.75rem",   { lineHeight: "1.125rem"                                              }], // 12px
        "micro":         ["0.6875rem", { lineHeight: "1rem",     letterSpacing: "0.03em",  fontWeight: "500" }], // 11px, uppercase eyebrow
      },
      // ── Spacing rhythm tokens ───────────────────────────────────────
      // Three named rhythm levels for card / section / page padding.
      // Component code uses `p-rhythm-tight` instead of guessing `p-3`
      // vs `p-4` — switches at the config layer.
      spacing: {
        "rhythm-tight":       "0.75rem",  // 12px — compact density
        "rhythm-comfortable": "1.25rem",  // 20px — default density
        "rhythm-loose":       "1.75rem",  // 28px — spacious density
      },
    },
  },
  plugins: [],
};

export default config;
