import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
    // THE PAGES ARE JSON, AND THE JIT ONLY COMPILES WHAT IT READS. Every
    // className a page uses lives in src/schemas/**/*.json; without this glob
    // 6,519 arbitrary classes on one real 15-page app reached the DOM with no
    // CSS behind them. This copy of the config is the THIRD producer of the
    // same globs (runtime_injector and app-foundation are the others) and was
    // the one that lost the fix — kept in step by hand until there is one.
    "./src/schemas/**/*.json",
    "./node_modules/@tentoroforge/library/**/*.{js,jsx,ts,tsx}",
    "./node_modules/@tentoroforge/renderer/**/*.{js,jsx,ts,tsx}",
    "./node_modules/@tentoroforge/engine/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        // Each status carries the locked 4-token shape (solid + foreground + subtle +
        // subtle-foreground), the same as app-foundation: a Badge reads `bg-success-subtle`,
        // and a config that does not map it renders the badge with no colour at all.
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
          subtle: "hsl(var(--destructive-subtle, 0 86% 97%))",
          "subtle-foreground": "hsl(var(--destructive-subtle-foreground, 0 74% 32%))",
        },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
          subtle: "hsl(var(--accent-subtle, var(--muted)))",
          "subtle-foreground": "hsl(var(--accent-subtle-foreground, var(--foreground)))",
        },
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
        // The dark surface for the one card that leads a screen, and the brand gradient's stops.
        inverse: {
          DEFAULT: "hsl(var(--inverse, 222 47% 11%))",
          foreground: "hsl(var(--inverse-foreground, 210 20% 98%))",
        },
        "gradient-start": "hsl(var(--gradient-start, var(--primary)))",
        "gradient-end": "hsl(var(--gradient-end, var(--accent)))",
        "gradient-foreground": "hsl(var(--gradient-foreground, var(--primary-foreground)))",
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        // A THIRD INK, A BRAND INK AND A HAIRLINE. The palette had `foreground`
        // and `muted-foreground` and one `border`, so everything quiet on a
        // page was the same quiet and every line was the same line. The app a
        // person designed by hand works four inks and keeps its hairline
        // separate from its structural border — `border-[#ece7f2]` is the
        // single most-used value in it, 77 times (CARES, 2026-11-04).
        // Passthrough roles, so they carry their own value, not a triplet.
        faint: "var(--ink-faint, hsl(var(--muted-foreground)))",
        brand: "var(--ink-brand, hsl(var(--primary)))",
        hairline: "var(--hairline, hsl(var(--border)))",
      },
      // The design's families (tokens.css): `font-heading` for titles, `font-sans` for the body.
      // A var() WITH A FALLBACK: an app whose design names no body face has no
      // `--font-body`, and a bare var() makes the whole font-family invalid at
      // computed time, so every page fell back to the browser's serif (PR #34 review).
      fontFamily: {
        sans: ["var(--font-body, ui-sans-serif)", "ui-sans-serif", "system-ui", "sans-serif"],
        heading: ["var(--font-heading, var(--font-body, ui-sans-serif))", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      // One `--radius` gave every app one corner, stepped by 2px. A designed
      // product cuts a card and a chip differently on purpose: CARES uses four
      // distinct radii (12, 24, 16, 14px). `designSystem.radius` is a record
      // and the projector already writes `--radius-<key>`; these are the keys
      // worth naming, each falling back to the single corner.
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        card: "var(--radius-card, var(--radius))",
        control: "var(--radius-control, calc(var(--radius) - 2px))",
        pill: "var(--radius-pill, 9999px)",
      },
      // THE DESIGN'S TYPE RAMP, AS CLASSES. `look_scale.type_scale_vars` works out
      // a modular scale per application from `typography.scaleMode` and writes it
      // to tokens.css — and until now nothing read it. tokens.css sets it on bare
      // `h1/h2/h3`, which any `text-2xl` on the element beats on specificity, and
      // on the one app measured every single heading carried one (Claimsdesk,
      // 28 of 28, 2026-11-04). So an `editorial` product and a `tight` console
      // drew their titles at exactly the same size. Named steps instead, so the
      // page author asks for the ROLE and the design decides the size.
      // Each var carries a fallback: a tree with no projected tokens still renders.
      fontSize: {
        display: ["var(--text-display, 3rem)", {
          lineHeight: "1.03", letterSpacing: "var(--tracking-display, -0.028em)",
        }],
        h1: ["var(--text-h1, 2rem)", {
          lineHeight: "1.15", letterSpacing: "var(--tracking-tight, -0.018em)",
        }],
        h2: ["var(--text-h2, 1.6rem)", {
          lineHeight: "1.2", letterSpacing: "var(--tracking-tight, -0.018em)",
        }],
        h3: ["var(--text-h3, 1.35rem)", { lineHeight: "1.3" }],
        body: ["var(--text-body, 1rem)", { lineHeight: "1.55" }],
        caption: ["var(--text-caption, 0.85rem)", { lineHeight: "1.45" }],
        // WHERE A DENSE PRODUCT ACTUALLY SPENDS ITS TYPE. The ramp had one step
        // below body and five above; 297 of CARES's 715 typographic decisions
        // are between 9px and 13px (2026-11-04). `label` is the table header,
        // the eyebrow, the field label; `micro` is the timestamp, the unit, the
        // chip. Without them every small thing on every page was `caption`.
        label: ["var(--text-label, 0.72rem)", {
          lineHeight: "1.35", letterSpacing: "var(--tracking-label, 0.08em)",
        }],
        micro: ["var(--text-micro, 0.625rem)", {
          lineHeight: "1.3", letterSpacing: "var(--tracking-label, 0.08em)",
        }],
      },
      letterSpacing: {
        tight: "var(--tracking-tight, -0.025em)",
        display: "var(--tracking-display, -0.035em)",
        // The only positive track. Every other one pulls in; a small-caps label
        // is the one thing that must be let out, and had no token at all.
        label: "var(--tracking-label, 0.08em)",
      },
      // Depth is the design's too, the same way, and for the same reason: the
      // ramp `designSystem.elevation` chooses reached tokens.css and stopped
      // there, so `shadow-md` was Tailwind's stock value in a flat console and a
      // dramatic luxe product alike. app-foundation's config has mapped these
      // since it was written (src/theme/tailwind-tokens.ts) — this copy, which
      // overwrites it in every generated app, never did.
      boxShadow: {
        sm: "var(--shadow-sm, 0 1px 2px 0 rgb(0 0 0 / 0.05))",
        DEFAULT: "var(--shadow-md, 0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1))",
        md: "var(--shadow-md, 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1))",
        lg: "var(--shadow-lg, 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1))",
        xl: "var(--shadow-xl, 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1))",
      },
      // The design's rhythm of space, as named steps beside Tailwind's numbers
      // (which are untouched, so `p-4` still means 1rem).
      spacing: {
        card: "var(--space-card-padding, 1rem)",
        section: "var(--space-section-gap, 1.5rem)",
        row: "var(--space-compact-row-padding, 0.5rem)",
      },
    },
  },
  plugins: [],
};

export default config;
