import type { RegisterBundle } from "./types";

export const figmaRegister: RegisterBundle = {
  name: "figma",
  description: "Vibrant, friendly, playful — design tools / creative apps.",
  tokens: {
    color: {
      primary: {
        "50":  "#fff1f2", "100": "#ffe4e6", "200": "#fecdd3", "300": "#fda4af",
        "400": "#fb7185", "500": "#f24e1e", "600": "#dc2626", "700": "#b91c1c",
        "800": "#991b1b", "900": "#7f1d1d", "950": "#450a0a",
      },
      secondary: {
        "50":  "#eff6ff", "100": "#dbeafe", "200": "#bfdbfe", "300": "#93c5fd",
        "400": "#60a5fa", "500": "#0d99ff", "600": "#1e40af", "700": "#1e3a8a",
        "800": "#172554", "900": "#0f172a", "950": "#020617",
      },
      accent: {
        "50":  "#f0fdf4", "100": "#dcfce7", "200": "#bbf7d0", "300": "#86efac",
        "400": "#4ade80", "500": "#a259ff", "600": "#16a34a", "700": "#15803d",
        "800": "#166534", "900": "#14532d", "950": "#052e16",
      },
      surface: { "0": "#ffffff", "1": "#f8fafc", "2": "#f1f5f9" },
      border:  { default: "#e4e4e7" },
      muted:   { default: "#a1a1aa" },
      text:    { primary: "#1c1917", secondary: "#52525b", tertiary: "#a1a1aa" },
      sidebar: { bg: "#1c1917", text: "#a1a1aa", active: "#f24e1e" },
    },
    typography: {
      font:     { body: "Inter, system-ui, sans-serif", heading: "Inter, system-ui, sans-serif" },
      display:  { family: "Inter, system-ui, sans-serif", weight: 800 },
      bodyText: { family: "Inter, system-ui, sans-serif", weight: 400, lineHeight: 1.5 },
      numeric:  { family: "Inter, system-ui, sans-serif", weight: 600, tabular: false },
      scaleMode: "balanced",
    },
    radius: { scale: "round" },
    density: "comfortable",
    elevation: "floating",
    motionLevel: "expressive",
  },
};
