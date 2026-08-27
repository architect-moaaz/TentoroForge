// packages/library/src/theme/registers/linear.ts
import type { RegisterBundle } from "./types";

export const linearRegister: RegisterBundle = {
  name: "linear",
  description: "Monochrome neutral, sharp edges, single accent — SaaS / dev tools.",
  tokens: {
    color: {
      primary: {
        "50":  "#fafafa", "100": "#f4f4f5", "200": "#e4e4e7", "300": "#d4d4d8",
        "400": "#a1a1aa", "500": "#5e6ad2", "600": "#4f5cc4", "700": "#3f4ab0",
        "800": "#323b8e", "900": "#252b6a", "950": "#171b46",
      },
      secondary: {
        "50":  "#fafafa", "100": "#f4f4f5", "200": "#e4e4e7", "300": "#d4d4d8",
        "400": "#a1a1aa", "500": "#71717a", "600": "#52525b", "700": "#3f3f46",
        "800": "#27272a", "900": "#18181b", "950": "#09090b",
      },
      surface: { "0": "#ffffff", "1": "#fafafa", "2": "#f4f4f5" },
      border:  { default: "#e4e4e7" },
      muted:   { default: "#a1a1aa" },
      text:    { primary: "#18181b", secondary: "#52525b", tertiary: "#a1a1aa" },
      sidebar: { bg: "#ffffff", text: "#52525b", active: "#5e6ad2" },
    },
    typography: {
      font:     { body: "Inter, system-ui, sans-serif", heading: "Inter, system-ui, sans-serif" },
      display:  { family: "Inter, system-ui, sans-serif", weight: 600 },
      bodyText: { family: "Inter, system-ui, sans-serif", weight: 400, lineHeight: 1.45 },
      numeric:  { family: "ui-monospace, SFMono-Regular, monospace", weight: 500, tabular: true },
      scaleMode: "tight",
    },
    radius: { scale: "sharp" },
    density: "compact",
    elevation: "flat",
    motionLevel: "subtle",
  },
};
