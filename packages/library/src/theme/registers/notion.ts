import type { RegisterBundle } from "./types";

export const notionRegister: RegisterBundle = {
  name: "notion",
  description: "Soft, airy, content-first — wikis / docs / knowledge bases.",
  tokens: {
    color: {
      primary: {
        "50":  "#fafaf9", "100": "#f5f5f4", "200": "#e7e5e4", "300": "#d6d3d1",
        "400": "#a8a29e", "500": "#78716c", "600": "#57534e", "700": "#44403c",
        "800": "#292524", "900": "#1c1917", "950": "#0c0a09",
      },
      secondary: {
        "50":  "#fafaf9", "100": "#f5f5f4", "200": "#e7e5e4", "300": "#d6d3d1",
        "400": "#a8a29e", "500": "#78716c", "600": "#57534e", "700": "#44403c",
        "800": "#292524", "900": "#1c1917", "950": "#0c0a09",
      },
      surface: { "0": "#ffffff", "1": "#fafaf9", "2": "#f5f5f4" },
      border:  { default: "#e7e5e4" },
      muted:   { default: "#a8a29e" },
      text:    { primary: "#1c1917", secondary: "#57534e", tertiary: "#a8a29e" },
      sidebar: { bg: "#fafaf9", text: "#57534e", active: "#1c1917" },
    },
    typography: {
      font:     { body: "ui-serif, Georgia, serif", heading: "ui-serif, Georgia, serif" },
      display:  { family: "ui-serif, Georgia, serif", weight: 600 },
      bodyText: { family: "ui-serif, Georgia, serif", weight: 400, lineHeight: 1.7 },
      numeric:  { family: "ui-sans-serif, system-ui", weight: 500, tabular: false },
      scaleMode: "dramatic",
    },
    radius: { scale: "round" },
    density: "spacious",
    elevation: "flat",
    motionLevel: "subtle",
  },
};
