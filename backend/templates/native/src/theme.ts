// The native theme — the web's design tokens, as numbers a StyleSheet takes.
//
// ONE SOURCE OF LOOK. The Blueprint's design system is projected twice: into
// the web app's CSS variables, and into `theme.generated.ts` for this app. The
// kit (src/ui) styles itself ONLY from `useTheme()`, so a palette change in the
// Blueprint reaches every screen, and a screen that wants a colour asks for a
// token (`theme.colors.primary`), never writes a hex.
//
// LIGHT ONLY in v1: the app's `userInterfaceStyle` is "light" and there is one
// palette. A screen that needs a dark variant is a design decision for the
// Blueprint, not something the kit guesses.

import { colors as generatedColors, radius as generatedRadius, fonts as generatedFonts } from "./theme.generated";
import { resolveColors, withAlpha, type ColorToken } from "./sdk/colors";

export type { ColorToken };

/** The spacing scale, in points. Use these, not literals: a screen's rhythm is one scale. */
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export type Space = keyof typeof space;

export interface Theme {
  colors: Record<ColorToken, string>;
  /** Corner radius of a control; cards use `radius + 4`, pills use `radiusPill`. */
  radius: number;
  radiusPill: number;
  space: typeof space;
  /** Font families when the app loads them; undefined is the system font. */
  fonts: { body?: string; heading?: string };
  /** Smallest touch target (points): iOS and Android both ask for 44. */
  touch: number;
  /** A colour with transparency (a scrim, a pressed state). */
  alpha: (token: ColorToken, alpha: number) => string;
}

function build(): Theme {
  const colors = resolveColors(generatedColors);
  const radius = Number.isFinite(generatedRadius) && generatedRadius >= 0 ? generatedRadius : 8;
  return {
    colors, radius, radiusPill: 999, space, fonts: generatedFonts ?? {}, touch: 44,
    alpha: (token, alpha) => withAlpha(colors[token], alpha),
  };
}

export const theme: Theme = build();

/** The theme. A hook so the call site reads like every other and a future
 *  provider (dark mode) changes this one function, not every component. */
export function useTheme(): Theme {
  return theme;
}
