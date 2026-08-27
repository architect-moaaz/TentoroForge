"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SplitArcPropsType } from "./SplitArc.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface SplitArcProps extends SplitArcPropsType {
  style?: StyleSlotT;
}

// 180° sweep centred at the top: left endpoint at 12-o'clock − 90° = 9-o'clock,
// right endpoint at 12-o'clock + 90° = 3-o'clock.
const SWEEP = 180;
const START = -90;

function polar(cx: number, cy: number, r: number, angleDeg: number): [number, number] {
  const a = ((angleDeg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}
function arcPath(cx: number, cy: number, r: number, startDeg: number, endDeg: number): string {
  const [x1, y1] = polar(cx, cy, r, startDeg);
  const [x2, y2] = polar(cx, cy, r, endDeg);
  const large = Math.abs(endDeg - startDeg) > 180 ? 1 : 0;
  const sweep = endDeg > startDeg ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} ${sweep} ${x2} ${y2}`;
}

function trendGlyph(t?: "up" | "down" | "flat"): string {
  if (t === "up")   return "▲";
  if (t === "down") return "▼";
  if (t === "flat") return "▬";
  return "";
}

/**
 * Half-arc gauge whose 180° sweep is split across ≥2 coloured segments —
 * the "received vs costs / income vs spend" shape seen on consumer utility
 * dashboards. Segments are proportional to their `value` (or you can pass
 * an explicit `total` to normalise). Endpoint values render under the arc
 * (with optional trend arrows); a dot legend sits below.
 *
 * Distinct from `Gauge` (single value, needle, thresholds) and from
 * `Chart` type=pie (full circle, no endpoint labels). Self-contained
 * inline SVG — CSP-safe, no external deps.
 */
export function SplitArc({
  segments,
  total,
  title,
  size = 220,
  stroke,
  showLegend = true,
  showEndLabels = true,
  style,
}: SplitArcProps) {
  const values = segments.map((s) => Math.max(0, Number(s.value) || 0));
  const sum = values.reduce((a, b) => a + b, 0);
  const denom = (total && total > 0 ? total : sum) || 1;

  const s = size;
  const cx = s / 2;
  const cy = s / 2;              // arc's centre — the sweep is above cy
  const strokeW = stroke ?? Math.max(10, s * 0.11);
  const r = cx - strokeW;

  // Segment arcs — cumulative angle across the sweep.
  const arcs: { d: string; color: string; midDeg: number; endDeg: number }[] = [];
  let cursor = START;
  for (let i = 0; i < segments.length; i++) {
    const frac = values[i] / denom;
    const arcLen = SWEEP * frac;
    const startDeg = cursor;
    const endDeg = cursor + arcLen;
    if (arcLen > 0.001) {
      arcs.push({
        d: arcPath(cx, cy, r, startDeg, endDeg),
        color: segments[i].color,
        midDeg: startDeg + arcLen / 2,
        endDeg,
      });
    }
    cursor = endDeg;
  }

  // SVG viewport — top half only + a little slack for stroke caps.
  const vbH = cy + strokeW; // don't draw the bottom half

  return (
    <div
      className="inline-flex flex-col items-stretch min-w-[220px]"
      data-splitarc=""
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {title && (
        <div className="text-sm font-medium text-muted-foreground mb-2">
          {title}
        </div>
      )}

      {showLegend && (
        <div className="flex items-center gap-3 mb-1 text-[11px]">
          {segments.map((seg, i) => (
            <div key={i} className="inline-flex items-center gap-1.5">
              <span
                aria-hidden
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: seg.color }}
              />
              <span className="text-muted-foreground">{seg.label}</span>
            </div>
          ))}
        </div>
      )}

      <svg
        width={s}
        height={vbH}
        viewBox={`0 0 ${s} ${vbH}`}
        role="img"
        aria-label={
          title ??
          segments
            .map((seg) => `${seg.label}: ${seg.value}${seg.endLabel ? ` (${seg.endLabel})` : ""}`)
            .join(", ")
        }
      >
        {/* Underlay track for the full sweep so unfilled space still shows a subtle arc. */}
        <path
          d={arcPath(cx, cy, r, START, START + SWEEP)}
          fill="none"
          stroke="var(--color-border-default, #e2e8f0)"
          strokeWidth={strokeW}
          strokeLinecap="butt"
          opacity={0.4}
        />
        {/* Segment arcs, drawn cumulatively. Rounded caps only on the OUTER
            edges (first segment's start + last segment's end); interior joins
            stay butt so segments abut cleanly. */}
        {arcs.map((a, i) => (
          <path
            key={i}
            d={a.d}
            fill="none"
            stroke={a.color}
            strokeWidth={strokeW}
            strokeLinecap={i === 0 || i === arcs.length - 1 ? "round" : "butt"}
          />
        ))}
      </svg>

      {showEndLabels && (
        <div className="flex justify-between items-baseline mt-1 text-xs">
          {/* Left endpoint = first segment's label; right endpoint = last */}
          <span
            className="tabular-nums font-medium text-foreground inline-flex items-center gap-1"
            style={{ color: segments[0]?.color }}
          >
            {trendGlyph(segments[0]?.trend)}{" "}
            {segments[0]?.endLabel ?? String(values[0] ?? "")}
          </span>
          <span
            className="tabular-nums font-medium text-foreground inline-flex items-center gap-1"
            style={{ color: segments[segments.length - 1]?.color }}
          >
            {trendGlyph(segments[segments.length - 1]?.trend)}{" "}
            {segments[segments.length - 1]?.endLabel ??
              String(values[values.length - 1] ?? "")}
          </span>
        </div>
      )}
    </div>
  );
}
