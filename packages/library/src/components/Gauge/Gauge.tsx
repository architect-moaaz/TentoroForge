"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { GaugePropsType } from "./Gauge.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface GaugeProps extends GaugePropsType {
  style?: StyleSlotT;
}

const SWEEP = 270;          // degrees of arc
const START = -135;         // start angle (0° = top, clockwise)
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));

// Point on a circle. angleDeg measured from 12-o'clock, clockwise positive.
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

/**
 * Radial KPI gauge — a 270° arc with optional colored threshold zones, a needle
 * at the current value, and a centered readout. Self-contained inline SVG (CSP
 * safe). Distinct from Progress (linear / plain circular): supports arbitrary
 * ranges, zone bands, and a target-style needle.
 */
export function Gauge({ value, min, max, label, unit, thresholds, size = 180, showValue = true, style }: GaugeProps) {
  const lo = min ?? 0;
  const hi = max ?? 100;
  const span = hi - lo || 1;
  const v = clamp(value ?? 0, lo, hi);
  const frac = (v - lo) / span;
  const valueDeg = START + SWEEP * frac;

  const s = size;
  const cx = s / 2;
  const cy = s / 2;
  const stroke = Math.max(8, s * 0.09);
  const r = cx - stroke;

  const zones = (thresholds && thresholds.length ? [...thresholds] : []).sort((a, b) => a.value - b.value);
  // Active color = the first zone whose upper bound >= value (else last zone / primary).
  const active = zones.find((z) => v <= z.value) ?? zones[zones.length - 1];
  const valueColor = active?.color ?? "var(--color-primary-500)";

  // Zone band segments (drawn on the track).
  const bands: { d: string; color: string }[] = [];
  let prev = lo;
  for (const z of zones) {
    const zStart = START + SWEEP * ((clamp(prev, lo, hi) - lo) / span);
    const zEnd = START + SWEEP * ((clamp(z.value, lo, hi) - lo) / span);
    if (zEnd > zStart) bands.push({ d: arcPath(cx, cy, r, zStart, zEnd), color: z.color });
    prev = z.value;
  }

  const [nx, ny] = polar(cx, cy, r - stroke * 0.2, valueDeg);

  return (
    <div className="inline-flex flex-col items-center" data-gauge="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <svg width={s} height={s * 0.82} viewBox={`0 0 ${s} ${s * 0.82}`} role="img" aria-label={label ? `${label}: ${v}${unit ?? ""}` : `${v}${unit ?? ""}`}>
        {/* track */}
        <path d={arcPath(cx, cy, r, START, START + SWEEP)} fill="none"
          stroke="var(--color-border-default, #e2e8f0)" strokeWidth={stroke} strokeLinecap="round" />
        {/* zone bands */}
        {bands.map((b, i) => (
          <path key={i} d={b.d} fill="none" stroke={b.color} strokeWidth={stroke} strokeLinecap="butt" opacity={0.35} />
        ))}
        {/* value arc */}
        <path d={arcPath(cx, cy, r, START, valueDeg)} fill="none" stroke={valueColor} strokeWidth={stroke} strokeLinecap="round" />
        {/* needle */}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="var(--color-text-primary, #0f172a)" strokeWidth={Math.max(2, stroke * 0.18)} strokeLinecap="round" />
        <circle cx={cx} cy={cy} r={Math.max(3, stroke * 0.3)} fill="var(--color-text-primary, #0f172a)" />
        {/* readout */}
        {showValue && (
          <text x={cx} y={cy + r * 0.55} textAnchor="middle" fontSize={s * 0.16} fontWeight={600} fill="var(--color-text-primary, #0f172a)">
            {Math.round(v * 10) / 10}{unit ?? ""}
          </text>
        )}
      </svg>
      {label && <span className="text-sm font-medium text-muted-foreground">{label}</span>}
    </div>
  );
}
