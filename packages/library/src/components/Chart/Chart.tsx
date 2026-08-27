"use client";

// packages/library/src/components/Chart/Chart.tsx
import * as React from "react";
import type { ChartPropsType } from "./Chart.schema";
import { LineChartImpl } from "./LineChart";
import { BarChartImpl } from "./BarChart";
import { AreaChartImpl } from "./AreaChart";
import { PieChartImpl } from "./PieChart";
import { FunnelChartImpl } from "./FunnelChart";
import { RadarChartImpl } from "./RadarChart";

export interface ChartProps extends ChartPropsType {}

/**
 * Chart dispatcher.
 *
 * Schema accepts `props.data` as either an inline array OR a Mustache
 * binding string (the LLM commonly emits `"{{stats.daily}}"` for live-data
 * bindings). When the binding hasn't been resolved by the runtime data
 * pipeline, `data` arrives as a string and recharts blows up with
 * `displayedData.map is not a function`. Guard with an empty-state.
 */
export function Chart(props: ChartProps) {
  if (!Array.isArray(props.data)) {
    return (
      <div
        style={{
          width: "100%",
          height: props.height ?? 240,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--color-text-tertiary, #94a3b8)",
          fontSize: 12,
          fontStyle: "italic",
        }}
        data-chart-placeholder
        // Canonical marker the render-truth probe reads. The legacy
        // data-chart-placeholder stays for anything already keying on it.
        data-forge-empty="chart"
      >
        {typeof props.data === "string"
          ? `Chart data binding ${props.data} — no fixture data available`
          : "Chart data unavailable"}
      </div>
    );
  }
  switch (props.chartType) {
    case "line":
      return <LineChartImpl {...props} />;
    case "bar":
      return <BarChartImpl {...props} />;
    case "area":
      return <AreaChartImpl {...props} />;
    case "pie":
    case "donut":
      return <PieChartImpl {...props} />;
    case "funnel":
      return <FunnelChartImpl {...props} />;
    case "radar":
      return <RadarChartImpl {...props} />;
    default:
      return <BarChartImpl {...props} />;
  }
}
