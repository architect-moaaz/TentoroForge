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
      },
      // The design's families (tokens.css): `font-heading` for titles, `font-sans` for the body.
      fontFamily: {
        sans: ["var(--font-body)", "ui-sans-serif", "system-ui", "sans-serif"],
        heading: ["var(--font-heading)", "var(--font-body)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
};

export default config;
