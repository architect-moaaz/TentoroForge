// packages/library/src/theme/registers/workday.ts
import type { RegisterBundle } from "./types";

/**
 * Workday-tier register — corporate enterprise feel.
 *
 * Visual language:
 *   - Navy primary, structured grays, muted accents
 *   - Density.compact: dense data tables, tight metric grids
 *   - Elevation.bordered: borders > shadows, structured cards
 *   - Radius.sharp (4px): rigid grid feel
 *   - Tabular numerics: aligned metric columns
 *   - Subtle motion: minimal animation
 *
 * Best for: HR, corporate admin, finance ops, compliance dashboards.
 */
export const workdayRegister: RegisterBundle = {
  name: "workday",
  description: "Corporate enterprise — dense, structured, navy-primary.",
  tokens: {
    color: {
      primary: {
        "50":  "#eff6ff", "100": "#dbeafe", "200": "#bfdbfe", "300": "#93c5fd",
        "400": "#60a5fa", "500": "#1d4ed8", "600": "#1e40af", "700": "#1e3a8a",
        "800": "#172554", "900": "#0f172a", "950": "#020617",
      },
      secondary: {
        "50":  "#f8fafc", "100": "#f1f5f9", "200": "#e2e8f0", "300": "#cbd5e1",
        "400": "#94a3b8", "500": "#64748b", "600": "#475569", "700": "#334155",
        "800": "#1e293b", "900": "#0f172a", "950": "#020617",
      },
      surface: { "0": "#ffffff", "1": "#f8fafc", "2": "#f1f5f9" },
      border:  { default: "#cbd5e1" },
      muted:   { default: "#94a3b8" },
      text:    { primary: "#0f172a", secondary: "#475569", tertiary: "#94a3b8" },
      sidebar: { bg: "#0f172a", text: "#cbd5e1", active: "#1e40af" },
    },
    typography: {
      font:   { body: "Inter, system-ui, sans-serif", heading: "Inter, system-ui, sans-serif" },
      display:  { family: "Inter, system-ui, sans-serif", weight: 700 },
      bodyText: { family: "Inter, system-ui, sans-serif", weight: 400, lineHeight: 1.45 },
      numeric:  { family: "ui-monospace, SFMono-Regular, monospace", weight: 600, tabular: true },
      scaleMode: "tight",
    },
    radius: { scale: "sharp" },
    density: "compact",
    elevation: "bordered",
    motionLevel: "subtle",
  },
};
