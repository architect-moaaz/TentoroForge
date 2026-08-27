// packages/library/src/components/MetricTile/MetricTile.figma.tsx
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { MetricTilePropsType } from "./MetricTile.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Figma-register MetricTile variant.
 *
 * Visual language:
 *   - Colorful rounded-2xl tile with shadow-lg (elevation.floating)
 *   - Vibrant shadow + hover:shadow-xl for expressive motion
 *   - Big bold numeric — weight 800 from display token
 *   - Bold uppercase tracking-wider label
 *   - Bold delta with directional arrow
 *   - density.comfortable spacing
 */

export interface FigmaMetricTileProps extends MetricTilePropsType {
  style?: StyleSlotT;
}

const TILE = "rounded-2xl border border-border bg-card text-card-foreground shadow-lg p-4 sm:p-6 flex flex-col gap-2 hover:shadow-xl transition-shadow overflow-hidden";
const LABEL = "text-xs font-bold uppercase tracking-wider text-muted-foreground";
const VALUE = "text-3xl font-extrabold leading-none tracking-tight text-foreground";
const DELTA = "inline-flex items-center gap-1 text-sm font-bold";

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

function fmtDelta(v: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 0,
    signDisplay: "never",
  }).format(Math.abs(v));
}

export function MetricTileFigma({
  label,
  value,
  format,
  delta,
  trend,
  style,
}: FigmaMetricTileProps) {
  const motionProps = useMotion(style?.motion);
  return (
    <div data-metric-tile="" className={TILE} style={resolveStyle(style)} {...motionProps}>
      <p data-metric-label className={LABEL}>{label}</p>
      <p data-metric-value className={VALUE}>{fmtValue(value, format)}</p>
      {delta && (
        <span className={`${DELTA} ${DELTA_TONE[delta.direction as keyof typeof DELTA_TONE]}`}>
          <span aria-hidden="true">{DELTA_GLYPH[delta.direction as keyof typeof DELTA_GLYPH]}</span>
          <span>{fmtDelta(typeof delta.value === "number" ? delta.value : parseFloat(delta.value))}</span>
        </span>
      )}
      {trend && trend.length > 0 && (
        <svg
          className="mt-2 h-8 w-full text-primary/70"
          viewBox={`0 0 ${trend.length * 10} 32`}
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <polyline
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            points={trend
              .map((v, i) => {
                const max = Math.max(...trend, 1);
                return `${i * 10},${32 - (v / max) * 28}`;
              })
              .join(" ")}
          />
        </svg>
      )}
    </div>
  );
}
