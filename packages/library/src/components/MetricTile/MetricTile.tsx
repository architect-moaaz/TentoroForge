import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { MetricTilePropsType } from "./MetricTile.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useTokens, useElevation, useRadiusScale } from "../../theme/tokens-context";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { resolveIcon } from "../../icons";

/**
 * Single-stat tile with optional delta indicator and sparkline trend.
 *
 * Uses shadcn-style Tailwind utilities so the tile matches the rest of the
 * generated app's design system without component-specific CSS.
 *
 * importance:
 *   primary   — 2× visual weight, larger text, tabular nums, bigger trend line
 *   secondary — default; matches today's appearance exactly
 *   tertiary  — compact, label-first, de-emphasised
 */

import { normalizeDelta } from "./delta";

export interface MetricTileProps extends MetricTilePropsType {
  style?: StyleSlotT;
}

function formatValue(value: number | string, format: MetricTilePropsType["format"]): string {
  // FIX-4 — distinguish "no data yet" from "value is zero". A binding that
  // never resolved (null/undefined/empty string) shipped as a shouting "0"
  // on every empty-DB first run; quiet it with an em-dash so a real zero
  // stays readable and the tile stops screaming failure.
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  switch (format) {
    case "number":
      return new Intl.NumberFormat("en-US").format(value);
    case "currency":
      return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD",
        maximumFractionDigits: 0 }).format(value);
    case "percent":
      return new Intl.NumberFormat("en-US", { style: "percent",
        maximumFractionDigits: 0 }).format(value);
    case "duration":
      // For numeric values, render as raw seconds. Callers wanting "2h 30m"
      // style output should pre-format the string and pass it as a string —
      // the early `typeof value === "string"` branch returns it untouched.
      return `${value}s`;
  }
}

const DELTA_GLYPH = { up: "↑", down: "↓", flat: "—" } as const;

// Map delta direction to a semantic text colour. up = success, down = destructive,
// flat = muted. Mirrors the colour system the generated app's globals.css ships.
// Use 700-series tones so delta text clears WCAG AA 4.5:1 on white card
// surfaces. emerald-600 (#059669) scores 3.76:1 — fails small-text AA; emerald-700
// (#047857) ~5.5:1 passes. `text-destructive` is a token (already governed by
// globals.css) so it stays — projects that need to bump destructive lift it in
// their token palette instead of here.
const DELTA_TONE: Record<"up" | "down" | "flat", string> = {
  up:   "text-emerald-700",
  down: "text-destructive",
  flat: "text-muted-foreground",
};

// Per-importance class sets — primary tiles are visually 2x weight; tertiary
// are demoted to label-first compact form. Defaults to "secondary" which
// matches today's appearance exactly so existing schemas don't shift.
const IMPORTANCE_CLASSES = {
  primary: {
    tile:  "relative flex flex-col gap-3 border bg-card p-4 md:p-8 text-card-foreground shadow-sm overflow-hidden",
    label: "text-sm font-semibold uppercase tracking-wide text-muted-foreground",
    value: "text-2xl md:text-4xl font-bold leading-tight tracking-tight text-foreground tabular-nums",
    delta: "inline-flex items-center gap-1.5 text-sm font-semibold",
  },
  secondary: {
    tile:  "relative flex flex-col gap-2 border bg-card p-4 md:p-6 text-card-foreground shadow-sm overflow-hidden",
    label: "text-xs font-medium uppercase tracking-wide text-muted-foreground",
    value: "text-xl md:text-2xl font-semibold leading-tight tracking-tight text-foreground",
    delta: "inline-flex items-center gap-1 text-xs font-medium",
  },
  tertiary: {
    tile:  "relative flex flex-col gap-1 border bg-card p-4 text-card-foreground",
    label: "text-[10px] font-medium uppercase tracking-wider text-muted-foreground",
    value: "text-lg font-medium leading-snug tracking-tight text-foreground",
    delta: "inline-flex items-center gap-1 text-[10px] font-medium",
  },
} as const;

// Elevation-aware border + shadow classes. "layered" is today's default
// (border + shadow-sm) and maps directly to the existing IMPORTANCE_CLASSES.
// Only non-layered elevations need an override — applied via data-elevation
// attribute on the element so Tailwind purges correctly.
const ELEVATION_SHADOW: Record<"flat"|"bordered"|"layered"|"floating", string> = {
  flat:     "!border-0 !shadow-none",
  bordered: "!shadow-none",     // keep border from cx.tile, strip shadow
  layered:  "",                 // no override — IMPORTANCE_CLASSES already correct
  floating: "!shadow-lg",       // keep border from cx.tile, upgrade shadow
};

// Slice A / KPI anatomy — pick the semantic tone from the threshold rule.
// Returns:
//   "critical" when the numeric value exceeds criticalAbove
//   "warn"     when it exceeds warnAbove (but not critical)
//   "ok"       otherwise
// A non-numeric value (unresolved mustache binding, string like "N/A")
// bypasses coloring so we never paint a placeholder red.
function pickThresholdTone(
  value: number | string,
  threshold: MetricTilePropsType["threshold"],
): "ok" | "warn" | "critical" {
  if (!threshold) return "ok";
  const numeric = typeof value === "number"
    ? value
    : Number.parseFloat(String(value).replace(/[^0-9.\-]/g, ""));
  if (!Number.isFinite(numeric)) return "ok";
  if (typeof threshold.criticalAbove === "number" && numeric > threshold.criticalAbove) {
    return "critical";
  }
  if (typeof threshold.warnAbove === "number" && numeric > threshold.warnAbove) {
    return "warn";
  }
  return "ok";
}

// Text-colour override for a threshold tone. Only applied when the
// threshold's `colorOnValue` is truthy; otherwise the data-threshold
// attribute is enough for custom app-level CSS to key off.
const THRESHOLD_VALUE_TONE: Record<"ok" | "warn" | "critical", string> = {
  ok:       "",
  warn:     "text-amber-600",
  critical: "text-destructive",
};

export function MetricTile({
  label, value, format, delta, icon, trend, importance, style,
  breakdown, threshold,
}: MetricTileProps) {
  const shownDelta = normalizeDelta(delta as never);
  const cx = IMPORTANCE_CLASSES[importance ?? "secondary"];
  const tokens = useTokens();
  const elevation = useElevation();

  // Typography.numeric drives the value rendering. Wave 1 importance classes
  // already set font-weight via Tailwind; we add fontFamily + tabular override
  // as inline style so importance still takes visual precedence on weight.
  // `numeric` is optional in compiled token sets (apps whose design-spec
  // typography carries no numeric block crash-looped every KPI tile here —
  // caught on a live generation). Undefined just means "inherit".
  const numeric = tokens.typography?.numeric;
  const valueStyle: React.CSSProperties = {
    fontFamily: numeric?.family,
    fontVariantNumeric: numeric?.tabular ? "tabular-nums" : undefined,
  };

  // For layered (default) elevationCls is "" — cx.tile already has the right
  // border + shadow-sm classes from IMPORTANCE_CLASSES.
  const elevationCls = ELEVATION_SHADOW[elevation];
  // Surface radius follows the project-wide radius.scale token (sharp/soft/
  // round) instead of a hardcoded rounded-lg — one of the strongest visible
  // per-app shape signals on dashboards.
  const radiusCls = RADIUS_SURFACE_CLASS[useRadiusScale()];
  const tileClass = [cx.tile, radiusCls, elevationCls].filter(Boolean).join(" ");

  // Slice A / KPI anatomy — threshold tone drives an optional text
  // colour override AND stamps `data-threshold` on the container so
  // custom app-level CSS can key off it independently.
  const thresholdTone = pickThresholdTone(value, threshold);
  const valueClass = threshold?.colorOnValue
    ? `${cx.value} ${THRESHOLD_VALUE_TONE[thresholdTone]}`
    : cx.value;

  return (
    <div
      data-metric-tile=""
      className={tileClass}
      style={resolveStyle(style)}
      data-importance={importance ?? "secondary"}
      data-elevation={elevation}
      data-threshold={threshold ? thresholdTone : undefined}
      {...useMotion(style?.motion)}
    >
      <p data-metric-label className={cx.label}>{label}</p>
      <p data-metric-value className={valueClass} style={valueStyle}>{formatValue(value, format)}</p>
      {breakdown && breakdown.length > 0 && (
        // Sub-info rows under the primary value. Two-column grid keeps
        // labels left-aligned + values right-aligned with tabular nums,
        // matching the Banking suite's "Male 984 / Female 1,016" pattern.
        // Muted by default so the primary value stays dominant.
        <dl
          data-metric-breakdown=""
          className="mt-1 grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 text-xs text-muted-foreground"
        >
          {breakdown.map((row, i) => (
            <React.Fragment key={i}>
              <dt data-metric-breakdown-label className="truncate">{row.label}</dt>
              <dd
                data-metric-breakdown-value
                className="text-right tabular-nums text-foreground/80 font-medium"
              >
                {typeof row.value === "number"
                  ? new Intl.NumberFormat("en-US").format(row.value)
                  : row.value}
              </dd>
            </React.Fragment>
          ))}
        </dl>
      )}
      {shownDelta && (
        <span
          className={`${cx.delta} ${DELTA_TONE[shownDelta.direction]}`}
          data-delta-direction={shownDelta.direction}
        >
          <span aria-hidden="true">{DELTA_GLYPH[shownDelta.direction]}</span>
          <span>{shownDelta.text}</span>
        </span>
      )}
      {trend && trend.length > 0 && (
        <div className="mt-2 text-muted-foreground/60" aria-hidden="true">
          <svg viewBox={`0 0 ${trend.length * 10} 30`} preserveAspectRatio="none"
               className={importance === "primary" ? "h-12 w-full" : "h-8 w-full"}>
            <polyline fill="none" stroke="currentColor" strokeWidth="1"
              points={trend.map((v, i) => {
                const max = Math.max(...trend, 1);
                return `${i * 10},${30 - (v / max) * 28}`;
              }).join(" ")} />
          </svg>
        </div>
      )}
      {icon && (() => {
        // Resolve the Lucide icon component. resolveIcon returns null for
        // unknown names — fall back to nothing rather than an empty span.
        // The `data-icon` attribute is preserved for testing + a11y.
        const IconComp = resolveIcon(icon);
        if (!IconComp) return null;
        return (
          <span
            className="absolute right-4 top-4 text-muted-foreground/70"
            data-icon={icon}
            aria-hidden="true"
          >
            <IconComp size={20} strokeWidth={1.5} />
          </span>
        );
      })()}
    </div>
  );
}
