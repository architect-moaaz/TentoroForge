import type { RadiusScale } from "../theme/token-types";

/**
 * Surface radius class per scale.
 *
 * Used by Card, Button, Input, Hero, Section, Alert, MetricTile, and other
 * non-pill components that should respond to the project-wide radius.scale
 * token. Components opt in by importing this map and reading the current
 * scale via `useRadiusScale()` from the tokens-context.
 *
 * Scale values match the design-system-overhaul spec: sharp = no radius,
 * soft = the default rounded-lg baseline, round = pronounced rounded-2xl
 * for Notion/Figma registers.
 */
export const RADIUS_SURFACE_CLASS: Record<RadiusScale, string> = {
  sharp: "rounded-none",
  soft:  "rounded-lg",
  round: "rounded-2xl",
};

/**
 * Pill shape — constant across scales. Badges, status pills, and avatar
 * borders use this; they are semantic affordances (round-on-purpose), not
 * styling that should bend to the radius scale.
 */
export const RADIUS_PILL_CLASS = "rounded-full" as const;
