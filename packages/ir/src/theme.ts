/**
 * Theme System — allows users to customize the visual appearance
 * by modifying the token → Tailwind mapping.
 *
 * Same IR compiles to different visual styles by changing the theme.
 */

import type { TokenMap } from "./types.js";

// ---------------------------------------------------------------------------
// Theme definitions
// ---------------------------------------------------------------------------

export interface ThemeDef {
  name: string;
  description: string;
  tokens: TokenMap;
  /** CSS variables to inject into globals.css */
  cssVariables: Record<string, string>;
}

const DEFAULT_THEME: ThemeDef = {
  name: "default",
  description: "Clean, neutral theme",
  tokens: {
    color: {
      primary: "#171717",
      secondary: "#737373",
      danger: "#dc2626",
      warning: "#d97706",
      success: "#16a34a",
      muted: "#6b7280",
    },
    spacing: { xs: "0.25rem", sm: "0.5rem", md: "1rem", lg: "1.5rem", xl: "2rem", "2xl": "3rem" },
    radius: { none: "0", sm: "0.25rem", md: "0.375rem", lg: "0.5rem", full: "9999px" },
  },
  cssVariables: {
    "--background": "0 0% 100%",
    "--foreground": "0 0% 3.9%",
    "--card": "0 0% 100%",
    "--card-foreground": "0 0% 3.9%",
    "--primary": "0 0% 9%",
    "--primary-foreground": "0 0% 98%",
    "--secondary": "0 0% 96.1%",
    "--secondary-foreground": "0 0% 9%",
    "--muted": "0 0% 96.1%",
    "--muted-foreground": "0 0% 45.1%",
    "--accent": "0 0% 96.1%",
    "--accent-foreground": "0 0% 9%",
    "--destructive": "0 84.2% 60.2%",
    "--destructive-foreground": "0 0% 98%",
    "--border": "0 0% 89.8%",
    "--input": "0 0% 89.8%",
    "--ring": "0 0% 3.9%",
    "--radius": "0.5rem",
  },
};

const OCEAN_THEME: ThemeDef = {
  name: "ocean",
  description: "Blue-toned professional theme",
  tokens: {
    color: {
      primary: "#2563eb",
      secondary: "#64748b",
      danger: "#ef4444",
      warning: "#f59e0b",
      success: "#22c55e",
      muted: "#94a3b8",
    },
  },
  cssVariables: {
    "--background": "210 40% 98%",
    "--foreground": "222.2 84% 4.9%",
    "--primary": "221.2 83.2% 53.3%",
    "--primary-foreground": "210 40% 98%",
    "--secondary": "210 40% 96.1%",
    "--secondary-foreground": "222.2 47.4% 11.2%",
    "--muted": "210 40% 96.1%",
    "--muted-foreground": "215.4 16.3% 46.9%",
    "--accent": "210 40% 96.1%",
    "--accent-foreground": "222.2 47.4% 11.2%",
    "--destructive": "0 84.2% 60.2%",
    "--destructive-foreground": "210 40% 98%",
    "--border": "214.3 31.8% 91.4%",
    "--ring": "221.2 83.2% 53.3%",
    "--radius": "0.5rem",
  },
};

const FOREST_THEME: ThemeDef = {
  name: "forest",
  description: "Green-toned natural theme",
  tokens: {
    color: {
      primary: "#16a34a",
      secondary: "#65a30d",
      danger: "#dc2626",
      warning: "#ca8a04",
      success: "#15803d",
      muted: "#6b7280",
    },
  },
  cssVariables: {
    "--background": "120 10% 98%",
    "--foreground": "150 30% 6%",
    "--primary": "142 76% 36%",
    "--primary-foreground": "120 10% 98%",
    "--secondary": "120 10% 95%",
    "--secondary-foreground": "150 30% 10%",
    "--muted": "120 10% 95%",
    "--muted-foreground": "150 10% 45%",
    "--accent": "120 10% 95%",
    "--accent-foreground": "150 30% 10%",
    "--border": "120 10% 90%",
    "--ring": "142 76% 36%",
    "--radius": "0.5rem",
  },
};

const SUNSET_THEME: ThemeDef = {
  name: "sunset",
  description: "Warm orange/amber theme",
  tokens: {
    color: {
      primary: "#ea580c",
      secondary: "#d97706",
      danger: "#dc2626",
      warning: "#ca8a04",
      success: "#16a34a",
      muted: "#78716c",
    },
  },
  cssVariables: {
    "--background": "30 20% 98%",
    "--foreground": "20 14.3% 4.1%",
    "--primary": "24.6 95% 53.1%",
    "--primary-foreground": "30 20% 98%",
    "--secondary": "30 20% 95%",
    "--secondary-foreground": "20 14.3% 10%",
    "--muted": "30 20% 95%",
    "--muted-foreground": "25 5.3% 44.7%",
    "--accent": "30 20% 95%",
    "--accent-foreground": "20 14.3% 10%",
    "--border": "30 15% 90%",
    "--ring": "24.6 95% 53.1%",
    "--radius": "0.5rem",
  },
};

const SHARP_THEME: ThemeDef = {
  name: "sharp",
  description: "No border radius, high contrast",
  tokens: {
    radius: { none: "0", sm: "0", md: "0", lg: "0", full: "0" },
    color: {
      primary: "#000000",
      secondary: "#525252",
      danger: "#b91c1c",
      warning: "#a16207",
      success: "#15803d",
      muted: "#737373",
    },
  },
  cssVariables: {
    ...DEFAULT_THEME.cssVariables,
    "--radius": "0px",
    "--primary": "0 0% 0%",
    "--border": "0 0% 80%",
  },
};

const PILL_THEME: ThemeDef = {
  name: "pill",
  description: "Fully rounded, soft appearance",
  tokens: {
    radius: { none: "0", sm: "0.5rem", md: "0.75rem", lg: "1rem", full: "9999px" },
  },
  cssVariables: {
    ...DEFAULT_THEME.cssVariables,
    "--radius": "1rem",
  },
};

// ---------------------------------------------------------------------------
// Industry-specific themes
// ---------------------------------------------------------------------------

const HEALTHCARE_THEME: ThemeDef = {
  name: "healthcare",
  description: "Clean, trustworthy healthcare theme — calming blues and greens",
  tokens: {
    color: {
      primary: "#0891b2",     // Teal — trust, calm, medical
      secondary: "#0e7490",
      danger: "#dc2626",      // Red for critical alerts
      warning: "#f59e0b",
      success: "#059669",     // Green for healthy/good status
      muted: "#6b7280",
    },
    radius: { none: "0", sm: "0.375rem", md: "0.5rem", lg: "0.75rem", full: "9999px" },
  },
  cssVariables: {
    "--background": "180 20% 99%",
    "--foreground": "200 20% 8%",
    "--primary": "192 91% 36%",
    "--primary-foreground": "180 20% 99%",
    "--secondary": "180 15% 95%",
    "--secondary-foreground": "200 20% 12%",
    "--muted": "180 15% 95%",
    "--muted-foreground": "200 10% 45%",
    "--accent": "170 60% 95%",
    "--accent-foreground": "200 20% 12%",
    "--destructive": "0 84.2% 60.2%",
    "--destructive-foreground": "0 0% 98%",
    "--border": "180 15% 90%",
    "--ring": "192 91% 36%",
    "--radius": "0.5rem",
  },
};

const FINANCE_THEME: ThemeDef = {
  name: "finance",
  description: "Conservative, professional finance theme — deep navy and gold accents",
  tokens: {
    color: {
      primary: "#1e3a5f",     // Deep navy — authority, stability
      secondary: "#475569",
      danger: "#b91c1c",
      warning: "#b45309",     // Gold/amber for warnings
      success: "#15803d",
      muted: "#64748b",
    },
    radius: { none: "0", sm: "0.25rem", md: "0.375rem", lg: "0.5rem", full: "9999px" },
  },
  cssVariables: {
    "--background": "220 20% 99%",
    "--foreground": "220 30% 10%",
    "--primary": "213 56% 24%",
    "--primary-foreground": "220 20% 98%",
    "--secondary": "220 15% 95%",
    "--secondary-foreground": "220 30% 12%",
    "--muted": "220 15% 95%",
    "--muted-foreground": "220 10% 45%",
    "--accent": "38 92% 50%",
    "--accent-foreground": "220 30% 10%",
    "--border": "220 15% 88%",
    "--ring": "213 56% 24%",
    "--radius": "0.375rem",
  },
};

const LOGISTICS_THEME: ThemeDef = {
  name: "logistics",
  description: "Bold, functional logistics theme — dark sidebar, orange accents",
  tokens: {
    color: {
      primary: "#c2410c",     // Burnt orange — energy, movement
      secondary: "#334155",   // Dark slate for sidebars
      danger: "#dc2626",
      warning: "#d97706",
      success: "#16a34a",
      muted: "#64748b",
    },
    radius: { none: "0", sm: "0.25rem", md: "0.375rem", lg: "0.5rem", full: "9999px" },
  },
  cssVariables: {
    "--background": "0 0% 98%",
    "--foreground": "215 28% 17%",
    "--primary": "21 90% 48%",
    "--primary-foreground": "0 0% 98%",
    "--secondary": "215 25% 95%",
    "--secondary-foreground": "215 28% 17%",
    "--muted": "215 25% 95%",
    "--muted-foreground": "215 16% 47%",
    "--accent": "215 25% 93%",
    "--accent-foreground": "215 28% 17%",
    "--border": "215 20% 88%",
    "--ring": "21 90% 48%",
    "--radius": "0.375rem",
  },
};

const CRM_THEME: ThemeDef = {
  name: "crm",
  description: "Vibrant sales/CRM theme — energetic purple-blue",
  tokens: {
    color: {
      primary: "#7c3aed",     // Purple — creativity, energy (like Salesforce/HubSpot)
      secondary: "#6366f1",   // Indigo
      danger: "#ef4444",
      warning: "#f59e0b",
      success: "#10b981",
      muted: "#6b7280",
    },
  },
  cssVariables: {
    "--background": "250 20% 99%",
    "--foreground": "250 30% 8%",
    "--primary": "263 70% 58%",
    "--primary-foreground": "250 20% 99%",
    "--secondary": "250 15% 95%",
    "--secondary-foreground": "250 30% 12%",
    "--muted": "250 15% 95%",
    "--muted-foreground": "250 10% 45%",
    "--accent": "250 80% 95%",
    "--accent-foreground": "250 30% 12%",
    "--border": "250 15% 90%",
    "--ring": "263 70% 58%",
    "--radius": "0.5rem",
  },
};

const EDUCATION_THEME: ThemeDef = {
  name: "education",
  description: "Friendly, approachable education theme — warm indigo",
  tokens: {
    color: {
      primary: "#4f46e5",     // Indigo — knowledge, depth
      secondary: "#7c3aed",
      danger: "#dc2626",
      warning: "#f59e0b",
      success: "#059669",
      muted: "#6b7280",
    },
    radius: { none: "0", sm: "0.375rem", md: "0.5rem", lg: "0.75rem", full: "9999px" },
  },
  cssVariables: {
    "--background": "240 15% 99%",
    "--foreground": "240 20% 8%",
    "--primary": "239 84% 67%",
    "--primary-foreground": "240 15% 99%",
    "--secondary": "240 12% 95%",
    "--secondary-foreground": "240 20% 12%",
    "--muted": "240 12% 95%",
    "--muted-foreground": "240 8% 45%",
    "--accent": "262 83% 95%",
    "--accent-foreground": "240 20% 12%",
    "--border": "240 12% 90%",
    "--ring": "239 84% 67%",
    "--radius": "0.5rem",
  },
};

const HR_THEME: ThemeDef = {
  name: "hr",
  description: "People-focused HR theme — warm, approachable rose-pink",
  tokens: {
    color: {
      primary: "#e11d48",     // Rose — people, warmth, engagement
      secondary: "#9f1239",
      danger: "#dc2626",
      warning: "#d97706",
      success: "#16a34a",
      muted: "#6b7280",
    },
  },
  cssVariables: {
    "--background": "350 15% 99%",
    "--foreground": "350 20% 8%",
    "--primary": "347 77% 50%",
    "--primary-foreground": "350 15% 99%",
    "--secondary": "350 12% 95%",
    "--secondary-foreground": "350 20% 12%",
    "--muted": "350 12% 95%",
    "--muted-foreground": "350 8% 45%",
    "--accent": "350 80% 95%",
    "--accent-foreground": "350 20% 12%",
    "--border": "350 12% 90%",
    "--ring": "347 77% 50%",
    "--radius": "0.5rem",
  },
};

const ECOMMERCE_THEME: ThemeDef = {
  name: "ecommerce",
  description: "Bold, conversion-focused e-commerce theme — vibrant green CTA",
  tokens: {
    color: {
      primary: "#059669",     // Emerald — buy, action, trust
      secondary: "#0d9488",
      danger: "#dc2626",
      warning: "#d97706",
      success: "#16a34a",
      muted: "#6b7280",
    },
  },
  cssVariables: {
    "--background": "0 0% 100%",
    "--foreground": "0 0% 5%",
    "--primary": "160 84% 39%",
    "--primary-foreground": "0 0% 100%",
    "--secondary": "160 10% 95%",
    "--secondary-foreground": "0 0% 10%",
    "--muted": "0 0% 96%",
    "--muted-foreground": "0 0% 45%",
    "--accent": "160 60% 95%",
    "--accent-foreground": "0 0% 10%",
    "--border": "0 0% 90%",
    "--ring": "160 84% 39%",
    "--radius": "0.5rem",
  },
};

const REALESTATE_THEME: ThemeDef = {
  name: "realestate",
  description: "Sophisticated real estate theme — slate blue with gold accents",
  tokens: {
    color: {
      primary: "#1e40af",     // Royal blue — trust, premium
      secondary: "#b45309",   // Gold — luxury, premium
      danger: "#dc2626",
      warning: "#d97706",
      success: "#16a34a",
      muted: "#64748b",
    },
  },
  cssVariables: {
    "--background": "220 15% 99%",
    "--foreground": "220 25% 8%",
    "--primary": "221 83% 40%",
    "--primary-foreground": "220 15% 99%",
    "--secondary": "220 12% 95%",
    "--secondary-foreground": "220 25% 12%",
    "--muted": "220 12% 95%",
    "--muted-foreground": "220 8% 45%",
    "--accent": "38 92% 95%",
    "--accent-foreground": "220 25% 12%",
    "--border": "220 12% 88%",
    "--ring": "221 83% 40%",
    "--radius": "0.375rem",
  },
};

const MANUFACTURING_THEME: ThemeDef = {
  name: "manufacturing",
  description: "Industrial, no-nonsense manufacturing theme — dark, high-contrast",
  tokens: {
    color: {
      primary: "#0f766e",     // Teal — industrial, precision
      secondary: "#334155",
      danger: "#dc2626",
      warning: "#d97706",
      success: "#16a34a",
      muted: "#64748b",
    },
    radius: { none: "0", sm: "0.125rem", md: "0.25rem", lg: "0.375rem", full: "9999px" },
  },
  cssVariables: {
    "--background": "180 5% 98%",
    "--foreground": "200 20% 10%",
    "--primary": "173 58% 39%",
    "--primary-foreground": "180 5% 98%",
    "--secondary": "200 15% 93%",
    "--secondary-foreground": "200 20% 12%",
    "--muted": "200 10% 94%",
    "--muted-foreground": "200 10% 45%",
    "--accent": "180 30% 94%",
    "--accent-foreground": "200 20% 12%",
    "--border": "200 10% 87%",
    "--ring": "173 58% 39%",
    "--radius": "0.25rem",
  },
};

// ---------------------------------------------------------------------------
// Theme registry
// ---------------------------------------------------------------------------

const THEMES: Record<string, ThemeDef> = {
  default: DEFAULT_THEME,
  ocean: OCEAN_THEME,
  forest: FOREST_THEME,
  sunset: SUNSET_THEME,
  sharp: SHARP_THEME,
  pill: PILL_THEME,
  // Industry themes
  healthcare: HEALTHCARE_THEME,
  finance: FINANCE_THEME,
  logistics: LOGISTICS_THEME,
  crm: CRM_THEME,
  education: EDUCATION_THEME,
  hr: HR_THEME,
  ecommerce: ECOMMERCE_THEME,
  realestate: REALESTATE_THEME,
  manufacturing: MANUFACTURING_THEME,
};

// ---------------------------------------------------------------------------
// Domain → Theme mapping
// ---------------------------------------------------------------------------

const DOMAIN_THEME_MAP: Record<string, string> = {
  "Healthcare": "healthcare",
  "Finance & Banking": "finance",
  "Logistics & Supply Chain": "logistics",
  "CRM": "crm",
  "Sales": "crm",
  "Education": "education",
  "Human Resources": "hr",
  "E-Commerce & Retail": "ecommerce",
  "Real Estate & Property": "realestate",
  "Manufacturing": "manufacturing",
  "Hospitality & Food": "sunset",
  "Legal": "finance",
  "Government": "sharp",
  "Non-Profit": "forest",
  "Media & Publishing": "ocean",
  "Agriculture": "forest",
  "Energy": "manufacturing",
  "Project Management": "ocean",
};

/**
 * Get the recommended theme name for a domain.
 * Falls back to "ocean" for unrecognized domains.
 */
export function getThemeForDomain(domain: string): string {
  return DOMAIN_THEME_MAP[domain] || "ocean";
}

/**
 * Get a theme by name. Returns the default theme if not found.
 */
export function getTheme(name: string): ThemeDef {
  return THEMES[name] || THEMES.default;
}

/**
 * List all available themes.
 */
export function listThemes(): Array<{ name: string; description: string }> {
  return Object.values(THEMES).map((t) => ({ name: t.name, description: t.description }));
}

/**
 * Generate CSS variables for a theme (for injection into globals.css).
 */
export function generateThemeCSS(themeName: string): string {
  const theme = getTheme(themeName);
  const vars = Object.entries(theme.cssVariables)
    .map(([key, value]) => `    ${key}: ${value};`)
    .join("\n");

  return `:root {\n${vars}\n}`;
}

/**
 * Merge a theme's tokens into an AppIR's token map.
 */
export function applyThemeTokens(appTokens: TokenMap, themeName: string): TokenMap {
  const theme = getTheme(themeName);
  return {
    ...appTokens,
    ...theme.tokens,
    color: { ...appTokens.color, ...theme.tokens.color } as TokenMap["color"],
    spacing: { ...appTokens.spacing, ...theme.tokens.spacing } as TokenMap["spacing"],
    radius: { ...appTokens.radius, ...theme.tokens.radius } as TokenMap["radius"],
    typography: { ...appTokens.typography, ...theme.tokens.typography } as TokenMap["typography"],
  };
}
