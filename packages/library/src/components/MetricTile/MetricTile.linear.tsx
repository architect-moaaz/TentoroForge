// packages/library/src/components/MetricTile/MetricTile.linear.tsx
import * as React from "react";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { MetricTilePropsType } from "./MetricTile.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { inferIcon, resolveIcon } from "../../icons";
import { normalizeDelta } from "./delta";

/**
 * Linear-register MetricTile variant.
 *
 * Visual language (Tier S + L refresh):
 *   - Card-surface tile with hairline border (was flat muted/40 — that read
 *     as "background paint" rather than "tile", so the four stat numbers
 *     melted into the page). Border-bordered tile reads as a real metric
 *     card without sacrificing Linear's data-first density.
 *   - Type-scale tokens drive label / value sizing (Tier S).
 *   - Optional Lucide icon next to the label — explicit `icon` prop wins;
 *     otherwise inferred from the label text (Pending → Clock, Approved →
 *     CheckCircle, Overdue → AlertTriangle, etc.).
 *   - Delta uses up/down/flat arrow Lucide glyphs rather than `+/−/·`
 *     unicode — reads cleaner and is consistent with the icon system.
 */

export interface LinearMetricTileProps extends MetricTilePropsType {
  style?: StyleSlotT;
}

const TILE = "flex flex-col gap-2 bg-card border border-border/60 rounded-xl px-6 py-4 hover:border-border transition-colors overflow-hidden";
const LABEL_ROW = "flex items-center gap-1.5 text-muted-foreground";
const LABEL = "text-micro uppercase";
const VALUE = "text-2xl font-semibold leading-tight tabular-nums text-foreground tracking-tight";
const DELTA = "inline-flex items-center gap-1 text-caption tabular-nums";

const DELTA_ICON = { up: ArrowUp, down: ArrowDown, flat: Minus } as const;
// 700-series for AA contrast on white card surface (see MetricTile.tsx note).
const DELTA_TONE: Record<"up" | "down" | "flat", string> = {
  up:   "text-emerald-700",
  down: "text-rose-700",
  flat: "text-muted-foreground",
};

function fmtValue(v: number | string, format: MetricTilePropsType["format"]): string {
  if (typeof v === "string") return v;
  if (format === "currency") return `$${new Intl.NumberFormat("en-US").format(v)}`;
  if (format === "percent")  return `${(v * 100).toFixed(0)}%`;
  if (format === "duration") return `${v}s`;
  return new Intl.NumberFormat("en-US").format(v);
}

export function MetricTileLinear({ label, value, format, delta, icon, style }: LinearMetricTileProps) {
  // Icon resolution: explicit `icon` prop wins; fall through to keyword
  // inference on the label so schemas that don't specify get sensible
  // defaults (clock for pending, check for completed, etc.).
  const Icon = resolveIcon(icon) ?? inferIcon(label);
  const shownDelta = normalizeDelta(delta as never);
  const DeltaIcon = shownDelta ? DELTA_ICON[shownDelta.direction] : null;
  return (
    <div data-metric-tile="" className={TILE} style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <div className={LABEL_ROW}>
        {Icon && <Icon className="h-3.5 w-3.5" aria-hidden="true" strokeWidth={2.25} />}
        <p data-metric-label className={LABEL}>{label}</p>
      </div>
      <p data-metric-value className={VALUE}>{fmtValue(value, format)}</p>
      {shownDelta && DeltaIcon && (
        <span className={`${DELTA} ${DELTA_TONE[shownDelta.direction]}`}>
          <DeltaIcon className="h-3 w-3" aria-hidden="true" />
          <span>{shownDelta.text}</span>
        </span>
      )}
    </div>
  );
}
