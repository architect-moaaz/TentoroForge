// packages/library/src/components/MetricTile/MetricTile.workday.tsx
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { MetricTilePropsType } from "./MetricTile.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { resolveIcon } from "../../icons";
import { useMotion } from "../../style/useMotion";
import { normalizeDelta } from "./delta";

/**
 * Workday-register MetricTile variant.
 *
 * Visual language:
 *   - Left-edge navy primary border (border-l-4 border-l-primary)
 *   - Hard border + no shadow (elevation.bordered + radius.sharp)
 *   - Tabular numerics with bigger weight contrast
 *   - Status sparkline below value (when trend present) gets stronger stroke
 *   - Compact tile (density.compact) — tight padding, tight gap
 */

export interface WorkdayMetricTileProps extends MetricTilePropsType {
  style?: StyleSlotT;
}

const TILE =
  "relative flex flex-col gap-1.5 border-l-4 border-l-primary border border-border " +
  "bg-card px-4 py-4 sm:px-5 text-card-foreground transition-colors overflow-hidden";
const LABEL =
  "text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground";
const VALUE =
  "text-2xl font-bold leading-none tracking-tight tabular-nums text-foreground";
const DELTA = "inline-flex items-center gap-1 text-[11px] font-semibold tabular-nums";

const DELTA_GLYPH = { up: "▲", down: "▼", flat: "—" } as const;
const DELTA_TONE: Record<"up" | "down" | "flat", string> = {
  up:   "text-emerald-700",
  down: "text-red-700",
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


export function MetricTileWorkday({
  label,
  value,
  format,
  delta,
  trend,
  icon,
  importance,
  style,
}: WorkdayMetricTileProps) {
  const shownDelta = normalizeDelta(delta as never);
  const motionProps = useMotion(style?.motion);
  // Honor the schema's visual-weight hierarchy — this variant used to
  // silently DROP icon + importance, flattening every dashboard's KPI row
  // to identical tiles (audited across generated apps).
  const primary = importance === "primary";
  return (
    <div
      data-metric-tile=""
      data-importance={importance ?? "secondary"}
      className={TILE + (primary ? " border-l-[6px]" : "")}
      style={resolveStyle(style)}
      {...motionProps}
    >
      {icon && (() => {
        const IconComp = resolveIcon(icon);
        if (!IconComp) return null;
        return (
          <span data-icon={icon} className="absolute right-4 top-4 text-muted-foreground/70" aria-hidden="true">
            <IconComp size={16} strokeWidth={2} />
          </span>
        );
      })()}
      <p data-metric-label className={LABEL}>{label}</p>
      <p data-metric-value className={primary ? VALUE.replace("text-2xl", "text-3xl") : VALUE}>{fmtValue(value, format)}</p>
      {shownDelta && (
        <span
          className={`${DELTA} ${DELTA_TONE[shownDelta.direction]}`}
          data-delta-direction={shownDelta.direction}
        >
          <span aria-hidden="true">{DELTA_GLYPH[shownDelta.direction]}</span>
          <span>{shownDelta.text}</span>
        </span>
      )}
      {trend && trend.length > 0 && (
        <svg
          className="mt-1 h-6 w-full text-muted-foreground/70"
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
