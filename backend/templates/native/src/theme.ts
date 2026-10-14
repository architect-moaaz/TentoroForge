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

import type { ViewStyle } from "react-native";
import { colors as generatedColors, radius as generatedRadius, fonts as generatedFonts } from "./theme.generated";
import { resolveColors, withAlpha, type ColorToken } from "./sdk/colors";

export type { ColorToken };

/** The spacing scale, in points. Use these, not literals: a screen's rhythm is one scale. */
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export type Space = keyof typeof space;

/** A typeface as the platforms need it: ONE FAMILY NAME PER WEIGHT. On Android and iOS a custom font is
 *  not "Inter, bold" but the file `Inter_700Bold`; `fontWeight` does not pick between files. */
export interface FontSet {
  regular: string;
  medium?: string;
  semibold?: string;
  bold?: string;
}

export type FontWeight = "regular" | "medium" | "semibold" | "bold";

/** Depth, as the platforms draw it: a soft shadow on iOS, `elevation` on Android. 0 is flat. */
export type Elevation = 0 | 1 | 2 | 3;

export interface Theme {
  colors: Record<ColorToken, string>;
  /** Corner radius of a control; cards use `radius + 4`, pills use `radiusPill`. */
  radius: number;
  radiusPill: number;
  space: typeof space;
  /** Typefaces when the app loads them (`fonts.generated.ts`); undefined is the system font. */
  fonts: { body?: FontSet; heading?: FontSet };
  /** The `fontFamily` for a weight of the body or heading face: `{}` on the system font, where
   *  `fontWeight` does the job. Falls back to the nearest weight the face has. */
  font: (weight: FontWeight, face?: "body" | "heading") => { fontFamily?: string };
  /** A soft shadow (see `Elevation`): spread it into a `style`. */
  shadow: (level: Elevation) => ViewStyle;
  /** Smallest touch target (points): iOS and Android both ask for 44. */
  touch: number;
  /** A colour with transparency (a scrim, a pressed state). */
  alpha: (token: ColorToken, alpha: number) => string;
}

const ORDER: FontWeight[] = ["regular", "medium", "semibold", "bold"];

/** The family for `weight`, or the nearest weight the face carries. */
function familyFor(set: FontSet | undefined, weight: FontWeight): string | undefined {
  if (!set) return undefined;
  const i = ORDER.indexOf(weight);
  for (let d = 0; d < ORDER.length; d++) {
    for (const j of [i - d, i + d]) {
      const name = j >= 0 && j < ORDER.length ? set[ORDER[j]] : undefined;
      if (name) return name;
    }
  }
  return set.regular;
}

const SHADOWS: Record<Elevation, ViewStyle> = {
  0: {},
  1: { shadowColor: "#0f172a", shadowOpacity: 0.06, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 1 },
  2: { shadowColor: "#0f172a", shadowOpacity: 0.1, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 3 },
  3: { shadowColor: "#0f172a", shadowOpacity: 0.16, shadowRadius: 20, shadowOffset: { width: 0, height: 8 }, elevation: 8 },
};

function build(): Theme {
  const colors = resolveColors(generatedColors);
  const radius = Number.isFinite(generatedRadius) && generatedRadius >= 0 ? generatedRadius : 8;
  const fonts = (generatedFonts ?? {}) as { body?: FontSet; heading?: FontSet };
  return {
    colors, radius, radiusPill: 999, space, fonts, touch: 44,
    alpha: (token, alpha) => withAlpha(colors[token], alpha),
    font: (weight, face = "body") => {
      const family = familyFor(face === "heading" ? fonts.heading ?? fonts.body : fonts.body, weight);
      return family ? { fontFamily: family } : {};
    },
    shadow: (level) => SHADOWS[level],
  };
}

export const theme: Theme = build();

/** The theme. A hook so the call site reads like every other and a future
 *  provider (dark mode) changes this one function, not every component. */
export function useTheme(): Theme {
  return theme;
}
