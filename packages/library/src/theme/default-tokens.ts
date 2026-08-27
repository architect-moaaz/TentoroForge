// Canonical token namespace. The LLM emits paths like
// `tokens.color.primary.500` and the prompt-builder + validator both derive
// the legal-paths list from this object. Changing keys here must be a
// coordinated change with services/schema_prompt.py and the renderer.

// TokenGroups is the structural contract for a token map.
// Using a recursive Record keeps the type compatible with both:
//   - dynamic access by string key (editor store's setTokenValue)
//   - passing defaultTokens directly without narrowing conflicts
// The snapshot test (not this type) is what locks the canonical key set.
//
// Wave 2: widened to permit string-typed top-level fields (density, elevation,
// motionLevel) alongside the nested object groups. Option A widening.
export type TokenGroups = {
  [K in keyof typeof defaultTokens]: typeof defaultTokens[K] extends string
    ? string
    : Record<string, any>;
} & Record<string, Record<string, any> | string>;

export const defaultTokens = {
  color: {
    primary: {
      "50":  "#eff6ff", "100": "#dbeafe", "200": "#bfdbfe", "300": "#93c5fd",
      "400": "#60a5fa", "500": "#3b82f6", "600": "#2563eb", "700": "#1d4ed8",
      "800": "#1e40af", "900": "#1e3a8a", "950": "#172554",
    },
    secondary: {
      "50":  "#f5f3ff", "100": "#ede9fe", "200": "#ddd6fe", "300": "#c4b5fd",
      "400": "#a78bfa", "500": "#8b5cf6", "600": "#7c3aed", "700": "#6d28d9",
      "800": "#5b21b6", "900": "#4c1d95", "950": "#2e1065",
    },
    accent: {
      "50":  "#fdf4ff", "100": "#fae8ff", "200": "#f5d0fe", "300": "#f0abfc",
      "400": "#e879f9", "500": "#d946ef", "600": "#c026d3", "700": "#a21caf",
      "800": "#86198f", "900": "#701a75", "950": "#4a044e",
    },
    surface: { "0": "#ffffff", "1": "#fafafa", "2": "#f4f4f5" },
    border:  { default: "#e4e4e7" },
    muted:   { default: "#a1a1aa" },
    text:    { primary: "#18181b", secondary: "#52525b", tertiary: "#a1a1aa" },
    sidebar: { bg: "#0f172a", text: "#cbd5e1", active: "#1e293b" },
    success: { "50": "#f0fdf4", "500": "#22c55e", "700": "#15803d" },
    warning: { "50": "#fffbeb", "500": "#f59e0b", "700": "#b45309" },
    error:   { "50": "#fef2f2", "500": "#ef4444", "700": "#b91c1c" },
    info:    { "50": "#eff6ff", "500": "#3b82f6", "700": "#1d4ed8" },
  },
  spacing: {
    "0":  "0",     "1":  "0.25rem", "2":  "0.5rem",  "3":  "0.75rem",
    "4":  "1rem",  "6":  "1.5rem",  "8":  "2rem",   "12": "3rem",
    "16": "4rem",  "24": "6rem",    "32": "8rem",   "48": "12rem",  "64": "16rem",
    semantic: {
      page: "2rem", card: "1.25rem", section: "4rem", element: "1rem", input: "0.75rem",
    },
  },
  radius: {
    sm: "0.25rem", md: "0.5rem", lg: "0.75rem", xl: "1rem", full: "9999px",
    // Wave 2: scale drives the radius family used by components. "soft" = today's md baseline.
    scale: "soft" as const,
  },
  shadow: {
    sm: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
    md: "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
    lg: "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
    xl: "0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)",
  },
  typography: {
    font:   { body: "Inter, system-ui, sans-serif", heading: "Inter, system-ui, sans-serif" },
    weight: { body: "400", heading: "600" },
    scale:  { h1: "2rem", h2: "1.5rem", h3: "1.25rem", body: "0.875rem", caption: "0.75rem" },
    lineHeight:    { tight: "1.25", normal: "1.5" },
    letterSpacing: { heading: "-0.02em", body: "0" },
    // Wave 2: new typography groups — defaults match today's appearance.
    display:   { family: "Inter, system-ui, sans-serif", weight: 700 },
    bodyText:  { family: "Inter, system-ui, sans-serif", weight: 400, lineHeight: 1.5 },
    numeric:   { family: "Inter, system-ui, sans-serif", weight: 500, tabular: false },
    scaleMode: "balanced" as const,
  },
  motion: {
    duration: { fast: "150ms", normal: "300ms" },
    easing:   { standard: "cubic-bezier(0.4, 0, 0.2, 1)" },
  },
  imagery: {
    login: "", dashboard: "",
    style: { emptyState: "geometric", icon: "outline", avatar: "initials" },
  },
  semantic: { status: {} as Record<string, string> },

  // Wave 2: new top-level scalar groups — defaults match today's appearance.
  // NOTE: `motionLevel` is the Wave 2 motion-intensity concept ("none"|"subtle"|"expressive").
  // It avoids collision with the existing `motion` object (animation duration/easing config).
  density:     "comfortable" as const,
  elevation:   "layered" as const,
  motionLevel: "subtle" as const,
} as const;
