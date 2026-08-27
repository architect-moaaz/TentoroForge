// packages/library/src/theme/registers/stripe.ts
import type { RegisterBundle } from "./types";

export const stripeRegister: RegisterBundle = {
  name: "stripe",
  description: "Two-tone with gradient hero, layered shadows — fintech / payments.",
  tokens: {
    color: {
      primary: {
        "50":  "#f5f3ff", "100": "#ede9fe", "200": "#ddd6fe", "300": "#c4b5fd",
        "400": "#a78bfa", "500": "#635bff", "600": "#5046e5", "700": "#3f37c0",
        "800": "#322b96", "900": "#252072", "950": "#15124a",
      },
      secondary: {
        "50":  "#f8fafc", "100": "#f1f5f9", "200": "#e2e8f0", "300": "#cbd5e1",
        "400": "#94a3b8", "500": "#64748b", "600": "#475569", "700": "#334155",
        "800": "#1e293b", "900": "#0f172a", "950": "#020617",
      },
      surface: { "0": "#ffffff", "1": "#f8fafc", "2": "#f1f5f9" },
      border:  { default: "#e4e4e7" },
      muted:   { default: "#a1a1aa" },
      text:    { primary: "#0a0a23", secondary: "#425466", tertiary: "#8898aa" },
      sidebar: { bg: "#0a0a23", text: "#cbd5e1", active: "#635bff" },
    },
    typography: {
      font:     { body: "Inter, system-ui, sans-serif", heading: "Inter, system-ui, sans-serif" },
      display:  { family: "Inter, system-ui, sans-serif", weight: 700 },
      bodyText: { family: "Inter, system-ui, sans-serif", weight: 400, lineHeight: 1.55 },
      numeric:  { family: "ui-monospace, SFMono-Regular, monospace", weight: 500, tabular: true },
      scaleMode: "balanced",
    },
    radius: { scale: "soft" },
    density: "comfortable",
    elevation: "layered",
    motionLevel: "subtle",
  },
};
