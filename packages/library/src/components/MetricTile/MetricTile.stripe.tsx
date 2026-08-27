// packages/library/src/components/MetricTile/MetricTile.stripe.tsx
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { MetricTilePropsType } from "./MetricTile.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { normalizeDelta } from "./delta";

/**
 * Stripe-register MetricTile variant.
 *
 * Visual language:
 *   - Gradient-tinted card (from-primary/5 to-card) with soft border + shadow-sm
 *   - Confident bold numeric (density.comfortable)
 *   - Prominent delta with color-coded direction
 *   - Rounded-md corners (radius.soft)
 *   - Layered shadow for depth (elevation.layered)
 */

export interface StripeMetricTileProps extends MetricTilePropsType {
  style?: StyleSlotT;
}

const TILE = "rounded-md border border-border bg-gradient-to-br from-primary/5 to-card text-card-foreground shadow-sm px-4 py-4 sm:px-5 flex flex-col gap-2 overflow-hidden";
const LABEL = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const VALUE = "text-3xl font-bold leading-none tracking-tight tabular-nums text-foreground";
const DELTA = "inline-flex items-center gap-1 text-xs font-semibold tabular-nums";

const DELTA_GLYPH = { up: "▲", down: "▼", flat: "—" } as const;
// 700-series for AA contrast on white card surface (see MetricTile.tsx note).
const DELTA_TONE: Record<"up" | "down" | "flat", string> = {
  up:   "text-emerald-700",
  down: "text-rose-700",
  flat: "text-muted-foreground",
};

function fmtValue(v: number | string, format: MetricTilePropsType["format"]): string {
  if (typeof v === "string") return v;
  if (format === "currency")
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(v);
  if (format === "percent")
    return new Intl.NumberFormat("en-US", {
      style: "percent",
      maximumFractionDigits: 0,
    }).format(v);
  if (format === "duration") return `${v}s`;
  return new Intl.NumberFormat("en-US").format(v);
}


export function MetricTileStripe({
  label,
  value,
  format,
  delta,
  trend,
  style,
}: StripeMetricTileProps) {
  const shownDelta = normalizeDelta(delta as never);
  const motionProps = useMotion(style?.motion);
  return (
    <div data-metric-tile="" className={TILE} style={resolveStyle(style)} {...motionProps}>
      <p data-metric-label className={LABEL}>{label}</p>
      <p data-metric-value className={VALUE}>{fmtValue(value, format)}</p>
      {shownDelta && (
        <span className={`${DELTA} ${DELTA_TONE[shownDelta.direction]}`}>
          <span aria-hidden="true">{DELTA_GLYPH[shownDelta.direction]}</span>
          <span>{shownDelta.text}</span>
        </span>
      )}
      {trend && trend.length > 0 && (
        <svg
          className="mt-1 h-6 w-full text-primary/60"
          viewBox={`0 0 ${trend.length * 10} 24`}
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <polyline
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            points={trend
              .map((v, i) => {
                const max = Math.max(...trend, 1);
                return `${i * 10},${24 - (v / max) * 22}`;
              })
              .join(" ")}
          />
        </svg>
      )}
    </div>
  );
}
