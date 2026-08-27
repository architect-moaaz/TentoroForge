/**
 * Shared helpers for anchor components.
 *
 * Anchors follow the same visual grammar: rounded surfaces, token-driven
 * colors, respect for density/radius/elevation from the theme. Keeping these
 * helpers small and shared prevents each anchor from reinventing the same
 * three lines and drifting.
 */

import { RADIUS_SURFACE_CLASS } from "../style/radius";
import { useDensity, useElevation, useRadiusScale } from "../theme/tokens-context";

/**
 * Compose surface classes from theme tokens. Every anchor's outer container
 * should call this so density/radius/elevation stay consistent app-wide.
 */
export function useSurfaceClasses(): string {
  const radiusCls = RADIUS_SURFACE_CLASS[useRadiusScale()];
  const densityCls = { compact: "p-4", comfortable: "p-6", spacious: "p-8" }[useDensity()];
  const elevationCls = { flat: "!border-0", bordered: "", layered: "shadow-sm", floating: "shadow-lg" }[useElevation()];
  return `border border-border bg-card ${radiusCls} ${densityCls} ${elevationCls}`;
}

/**
 * Skeleton line — the fallback when a bound value is loading/missing.
 * Never render an anchor with a blank slot; always render this shimmer.
 */
export function skeleton(widthClass = "w-24"): string {
  return `inline-block h-4 ${widthClass} rounded bg-muted animate-pulse align-middle`;
}
