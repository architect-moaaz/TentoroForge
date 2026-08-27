import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { StaggerPropsType } from "./Stagger.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotionLevel } from "../../theme/tokens-context";
import { MOTION_ENVELOPE } from "../../style/motion-tokens";

/**
 * Wraps children with a staggered reveal. Each direct child gets a fade-up
 * animation delayed by `interval * index`.
 *
 * Respects the motionLevel token:
 *   - "none"       → renders children with no animation wrapper
 *   - "subtle"     → 30ms stagger gap (tight, default appearance)
 *   - "expressive" → 80ms stagger gap (more dramatic reveals)
 *
 * The `interval` prop overrides the envelope's staggerGap when provided.
 *
 * Emitted classnames + data attributes:
 *
 *   <div class="motion-wrapper" data-motion="stagger"
 *        style="--stagger-interval: <interval>ms; --stagger-delay: <delay>ms">
 *     <div class="motion-stagger-item" style="--motion-stagger-i: 0">{child[0]}</div>
 *     <div class="motion-stagger-item" style="--motion-stagger-i: 1">{child[1]}</div>
 *     ...
 */
export interface StaggerProps extends StaggerPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function Stagger({ delay, interval, style, children }: StaggerProps) {
  const motionLevel = useMotionLevel();
  const env = MOTION_ENVELOPE[motionLevel];

  // When motion is disabled, render children without any animation wrapper.
  if (!env.enabled) {
    return <>{children}</>;
  }

  // Use prop override when provided; fall back to envelope stagger gap.
  // interval has a default(80) at the schema level when parsed through
  // the schema; component still defaults defensively to env.staggerGap.
  const ivl = interval ?? env.staggerGap;

  const css: React.CSSProperties = {
    ...resolveStyle(style),
    ["--stagger-interval" as any]: `${ivl}ms`,
    // Ease driven from envelope.
    ["--stagger-ease" as any]: env.ease,
    ...(delay !== undefined ? { ["--stagger-delay" as any]: `${delay}ms` } : {}),
  };
  const items = React.Children.toArray(children);
  return (
    <div className="motion-wrapper" data-motion="stagger" style={css}>
      {items.map((child, i) => (
        <div key={i} className="motion-stagger-item"
             style={{ ["--motion-stagger-i" as any]: i }}>
          {child}
        </div>
      ))}
    </div>
  );
}
