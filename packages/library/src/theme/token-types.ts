// packages/library/src/theme/token-types.ts
/**
 * Type definitions for the expanded token system.
 *
 * Defaults match today's appearance — adding a new group with its default
 * value is a no-op visually. Wave 3 stylistic registers override these
 * defaults to produce different design "personalities" (Workday/Linear/etc).
 *
 * NOTE on naming: the existing `defaultTokens.motion` key holds animation
 * timing config (duration, easing). The new Wave 2 "motion intensity" concept
 * lives under `defaultTokens.motionLevel` to avoid collision. `ExpandedTokens`
 * exposes it as `motion` for the logical API surface; `useMotionLevel()` reads
 * from `motionLevel` internally.
 */

export type RadiusScale = "sharp" | "soft" | "round";
export type Density = "compact" | "comfortable" | "spacious";
export type Elevation = "flat" | "bordered" | "layered" | "floating";
export type Motion = "none" | "subtle" | "expressive";
export type ScaleMode = "tight" | "balanced" | "dramatic";

export interface TypographyDisplay {
  family: string;
  weight: number;
}
export interface TypographyBodyText {
  family: string;
  weight: number;
  lineHeight: number;
}
export interface TypographyNumeric {
  family: string;
  weight: number;
  tabular: boolean;
}

/** Type guard / runtime accessor for the new Wave 2 groups. */
export interface ExpandedTokens {
  radius: { scale: RadiusScale };
  typography: {
    display: TypographyDisplay;
    bodyText: TypographyBodyText;
    numeric: TypographyNumeric;
    scaleMode: ScaleMode;
  };
  density: Density;
  elevation: Elevation;
  /** Motion intensity level (not the animation timing config in `motion.duration`). */
  motion: Motion;
}
