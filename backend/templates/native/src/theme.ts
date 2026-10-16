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
import {
  colors as generatedColors, radius as generatedRadius, fonts as generatedFonts, radii as generatedRadii,
  spacing as generatedSpacing, pagePadding as generatedPagePadding, shadows as generatedShadows,
  typeScale as generatedTypeScale, borderWidth as generatedBorderWidth, heading as generatedHeading,
} from "./theme.generated";
import { resolveColors, toColor, withAlpha, type ColorToken } from "./sdk/colors";

export type { ColorToken };

/** The spacing scale, in points - THE DESIGN'S (`designSystem.spacing`, by its density). Use these, never a
 *  literal: a screen's rhythm is one scale, and a design that asks for compact gets it everywhere. */
export const space: { readonly xs: number; readonly sm: number; readonly md: number; readonly lg: number; readonly xl: number; readonly xxl: number } = generatedSpacing;
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
  /** Corner radius of a control (the design's `md`); pills use `radiusPill`. */
  radius: number;
  /** The design's three corner radii: `sm` a small box, `md` a control, `lg` a card or a sheet. */
  radii: { readonly sm: number; readonly md: number; readonly lg: number };
  radiusPill: number;
  /** The margin around a screen's content (the design's `page-padding`). */
  pagePadding: number;
  /** A hairline's width: the design's `border-width`. */
  borderWidth: number;
  /** The kit's type scale is multiplied by this: the design's base size over 16. */
  typeScale: number;
  /** The design's brand gradient, start to end (the web's `bg-brand-gradient`): its `gradientStart` and `gradientEnd`
   *  when it names them, else the primary colour into the accent. A hero band is drawn with it. */
  gradient: readonly [string, string];
  /** How the design's headings look: weight, colour (a tone) and a page title's size (null: the kit's). */
  heading: { readonly weight: "regular" | "medium" | "semibold" | "bold"; readonly tone: "default" | "primary" | "accent"; readonly titleSize: number | null };
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

function build(): Theme {
  const colors = resolveColors(generatedColors);
  const raw = generatedColors as Readonly<Record<string, string | undefined>>;
  const fonts = (generatedFonts ?? {}) as { body?: FontSet; heading?: FontSet };
  return {
    colors, radius: Number.isFinite(generatedRadius) && generatedRadius >= 0 ? generatedRadius : generatedRadii.md,
    radii: generatedRadii, radiusPill: 999, pagePadding: generatedPagePadding, borderWidth: generatedBorderWidth,
    typeScale: generatedTypeScale > 0 ? generatedTypeScale : 1, heading: generatedHeading, space, fonts, touch: 44,
    gradient: [
      raw.gradientStart ? toColor(raw.gradientStart) : colors.primary,
      raw.gradientEnd ? toColor(raw.gradientEnd) : colors.accent,
    ],
    alpha: (token, alpha) => withAlpha(colors[token], alpha),
    font: (weight, face = "body") => {
      const family = familyFor(face === "heading" ? fonts.heading ?? fonts.body : fonts.body, weight);
      return family ? { fontFamily: family } : {};
    },
    shadow: (level) => (level === 0 ? {} : (generatedShadows[level] as ViewStyle)),
  };
}

export const theme: Theme = build();

/** The theme. A hook so the call site reads like every other and a future
 *  provider (dark mode) changes this one function, not every component. */
export function useTheme(): Theme {
  return theme;
}
