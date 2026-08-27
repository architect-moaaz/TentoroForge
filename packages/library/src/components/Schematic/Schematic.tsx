"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SchematicPropsType } from "./Schematic.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface SchematicProps extends SchematicPropsType {
  style?: StyleSlotT;
}

const DEFAULT_STATUS_COLORS: Record<string, string> = {
  ok: "var(--color-success-500, #22c55e)",
  active: "var(--color-primary-500)",
  busy: "var(--color-warning-500, #f59e0b)",
  warning: "var(--color-warning-500, #f59e0b)",
  error: "var(--color-danger-500, #ef4444)",
  blocked: "var(--color-danger-500, #ef4444)",
  idle: "var(--color-border-strong, #94a3b8)",
};

/**
 * Schematic map — a self-contained SVG floor plan / zone map / route diagram
 * (warehouse bins, store floor, station layout, delivery zones). Not a geographic
 * tile map (CSP forbids external tiles): callers pass marker/region coordinates in
 * an abstract WIDTH×HEIGHT space. Renders grid + regions + status-coloured markers.
 */
export function Schematic({
  width = 100, height = 60, grid, regions, markers,
  statusColors, showLabels = true, heightPx = 320, style,
}: SchematicProps) {
  const pts = Array.isArray(markers) ? markers : [];
  const colors = { ...DEFAULT_STATUS_COLORS, ...(statusColors ?? {}) };
  const markerColor = (m: any): string =>
    m.color ?? (m.status && colors[m.status]) ?? "var(--color-primary-500)";
  const r = Math.max(0.8, Math.min(width, height) * 0.018);
  const usedStatuses = Array.from(new Set(pts.map((m: any) => m.status).filter(Boolean)));

  return (
    <div className="w-full" data-schematic="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={heightPx}
        preserveAspectRatio="xMidYMid meet"
        style={{ background: "var(--color-surface-sunken, #f8fafc)", borderRadius: 8, border: "1px solid var(--color-border-default, #e2e8f0)" }}>
        {/* grid */}
        {grid && (
          <g stroke="var(--color-border-default, #e2e8f0)" strokeWidth={0.15}>
            {Array.from({ length: grid.cols + 1 }, (_, i) => {
              const x = (width / grid.cols) * i;
              return <line key={`c${i}`} x1={x} y1={0} x2={x} y2={height} />;
            })}
            {Array.from({ length: grid.rows + 1 }, (_, i) => {
              const y = (height / grid.rows) * i;
              return <line key={`r${i}`} x1={0} y1={y} x2={width} y2={y} />;
            })}
          </g>
        )}
        {/* regions */}
        {(regions ?? []).map((rg, i) => {
          const fill = rg.color ?? "var(--color-primary-500)";
          const cx = rg.points
            ? rg.points.reduce((s, p) => s + p[0], 0) / rg.points.length
            : (rg.x ?? 0) + (rg.w ?? 0) / 2;
          const cy = rg.points
            ? rg.points.reduce((s, p) => s + p[1], 0) / rg.points.length
            : (rg.y ?? 0) + (rg.h ?? 0) / 2;
          return (
            <g key={rg.id ?? i}>
              {rg.points ? (
                <polygon points={rg.points.map((p) => p.join(",")).join(" ")} fill={fill} fillOpacity={0.14} stroke={fill} strokeWidth={0.3} />
              ) : (
                <rect x={rg.x ?? 0} y={rg.y ?? 0} width={rg.w ?? 0} height={rg.h ?? 0} rx={0.8} fill={fill} fillOpacity={0.14} stroke={fill} strokeWidth={0.3} />
              )}
              {showLabels && rg.label && (
                <text x={cx} y={cy} textAnchor="middle" dominantBaseline="middle" fontSize={Math.max(1.6, height * 0.035)} fill="var(--color-text-secondary, #475569)">{rg.label}</text>
              )}
            </g>
          );
        })}
        {/* markers */}
        {pts.map((m: any, i: number) => {
          const c = markerColor(m);
          const shape = m.shape ?? "circle";
          return (
            <g key={m.id ?? i}>
              {shape === "square" ? (
                <rect x={m.x - r} y={m.y - r} width={r * 2} height={r * 2} rx={r * 0.3} fill={c} />
              ) : shape === "pin" ? (
                <path d={`M ${m.x} ${m.y} l ${-r} ${-r * 1.6} a ${r} ${r} 0 1 1 ${r * 2} 0 z`} fill={c} />
              ) : (
                <circle cx={m.x} cy={m.y} r={r} fill={c} />
              )}
              {showLabels && m.label && (
                <text x={m.x} y={m.y - r * 1.4} textAnchor="middle" fontSize={Math.max(1.4, height * 0.03)} fill="var(--color-text-primary, #0f172a)">{m.label}</text>
              )}
            </g>
          );
        })}
      </svg>
      {/* legend */}
      {usedStatuses.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-3">
          {usedStatuses.map((st) => (
            <span key={st} className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: colors[st] ?? "var(--color-primary-500)" }} />
              {st}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
