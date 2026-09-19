"use client";

// packages/library/src/components/Chart/Chart.tsx
import * as React from "react";
import type { ChartPropsType } from "./Chart.schema";
import { EChart, type ChartSelection } from "./EChart";

export type { ChartSelection } from "./EChart";

export interface ChartProps extends ChartPropsType {
  // A click on a bar, point, slice or cell — drill down or cross-filter.
  onSelect?: (selection: ChartSelection) => void;
  className?: string;
}

function Placeholder({ height, children }: { height?: number; children: React.ReactNode }) {
  return (
    <div
      style={{
        width: "100%",
        height: height ?? 240,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "hsl(var(--muted-foreground))",
        fontSize: 12,
      }}
      data-chart-placeholder
      // Canonical marker the render-truth probe reads. The legacy
      // data-chart-placeholder stays for anything already keying on it.
      data-forge-empty="chart"
    >
      {children}
    </div>
  );
}

/**
 * Every chart the library draws — bar, line, area, pie, donut, funnel, radar,
 * scatter, heatmap and treemap — on ECharts (`EChart`).
 *
 * Schema accepts `props.data` as either an inline array OR a Mustache
 * binding string (`"{{stats.daily}}"`). When the binding hasn't been resolved
 * by the runtime data pipeline, `data` arrives as a string; that, and an empty
 * array, render a quiet empty state instead of blank axes.
 */
export function Chart(props: ChartProps) {
  if (!Array.isArray(props.data)) {
    return (
      <Placeholder height={props.height}>
        <span style={{ fontStyle: "italic" }}>
          {typeof props.data === "string"
            ? `Chart data binding ${props.data} — no fixture data available`
            : "Chart data unavailable"}
        </span>
      </Placeholder>
    );
  }
  if (props.data.length === 0) {
    return <Placeholder height={props.height}>No data for this period yet</Placeholder>;
  }
  return <EChart {...props} />;
}
