import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { FadeInPropsType } from "./FadeIn.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotionLevel } from "../../theme/tokens-context";
import { MOTION_ENVELOPE } from "../../style/motion-tokens";

/**
 * Wraps children with a fade-in animation. Delay/duration override
 * the global stylesheet defaults via CSS custom properties.
 *
 * Respects the motionLevel token:
 *   - "none"       → renders children with no animation wrapper
 *   - "subtle"     → 200ms ease (default appearance, matches prior behaviour)
 *   - "expressive" → 400ms overshoot ease
 *
 * Emitted classnames + data attributes:
 *
 *   <div class="motion-wrapper" data-motion="fade-in"
 *        style="--fadein-delay: <delay>ms; --fadein-duration: <duration>ms">
 *     {children}
 */
export interface FadeInProps extends FadeInPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function FadeIn({ delay, duration, style, children }: FadeInProps) {
  const motionLevel = useMotionLevel();
  const env = MOTION_ENVELOPE[motionLevel];

  // When motion is disabled, render children without any animation wrapper.
  if (!env.enabled) {
    return <>{children}</>;
  }

  // Use prop overrides when provided; fall back to envelope values.
  const resolvedDuration = duration ?? env.duration;

  const css: React.CSSProperties = {
    ...resolveStyle(style),
    // Duration: inline prop wins over envelope, envelope wins over CSS default.
    ["--fadein-duration" as any]: `${resolvedDuration}ms`,
    // Ease: drive from envelope (CSS variable override for the animation).
    ["--fadein-ease" as any]: env.ease,
    ...(delay !== undefined ? { ["--fadein-delay" as any]: `${delay}ms` } : {}),
  };
  return (
    <div className="motion-wrapper" data-motion="fade-in" style={css}>
      {children}
    </div>
  );
}
