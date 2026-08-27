// packages/library/src/components/MetricTile/MetricTile.notion.tsx
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { MetricTilePropsType } from "./MetricTile.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { normalizeDelta } from "./delta";

/**
 * Notion-register MetricTile variant.
 *
 * Visual language:
 *   - Generous padding, rounded-lg (radius.round 12px), no border, no shadow (elevation.flat)
 *   - Serif typography — content-first, no uppercase labels, no tracking-wide
 *   - Clean layout with soft background tile
 *   - No sparkline — Notion is prose/content-first, not data-viz-first
 *   - Subtle delta in normal weight
 */

export interface NotionMetricTileProps extends MetricTilePropsType {
  style?: StyleSlotT;
}

const TILE = "rounded-lg bg-card p-4 sm:p-6 flex flex-col gap-2 overflow-hidden";
const LABEL = "text-xs font-normal text-muted-foreground tracking-normal";
const VALUE = "text-2xl font-semibold leading-tight tracking-tight text-foreground";
const DELTA = "inline-flex items-center gap-1 text-xs font-normal";

const DELTA_GLYPH = { up: "↑", down: "↓", flat: "→" } as const;
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


export function MetricTileNotion({
  label,
  value,
  format,
  delta,
  style,
}: NotionMetricTileProps) {
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
    </div>
  );
}
