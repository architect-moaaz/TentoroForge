"use client";

// packages/library/src/components/Chart/PieChart.tsx
import * as React from "react";
import { PieChart as RePieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from "recharts";
import type { ChartPropsType } from "./Chart.schema";
import { useTokens } from "../../theme/tokens-context";

const DEFAULT_PALETTE = [
  "hsl(var(--primary))",
  "hsl(var(--accent))",
  "hsl(var(--success))",
  "hsl(var(--warning))",
  "hsl(var(--info))",
  "hsl(var(--destructive))",
  "var(--color-primary-300, hsl(var(--primary) / 0.5))",
  "var(--color-accent-300,  hsl(var(--accent) / 0.5))",
];

/** Pie / donut. Each row is a slice: value = first series' dataKey (default
 *  "value"), label = xKey (default "label") — matches the op:"series" shape. */
export function PieChartImpl(props: ChartPropsType) {
  const tokens = useTokens();
  const numericFamily = tokens.typography?.numeric?.family;
  const data = Array.isArray(props.data) ? props.data : [];
  const valueKey = props.series?.[0]?.dataKey ?? "value";
  const nameKey = props.xKey ?? "label";
  const donut = props.chartType === "donut";
  return (
    <div style={{ width: "100%", height: props.height ?? 240, fontFamily: numericFamily }}>
      <ResponsiveContainer>
        <RePieChart>
          {props.showTooltip !== false && <Tooltip />}
          {props.showLegend !== false && <Legend wrapperStyle={{ fontSize: 11 }} />}
          <Pie
            // recharts 2.15's entry animation goes through react-smooth's
            // Animate, which does not survive React 19 — the series element
            // mounts but renders an EMPTY <g>, so a chart with correct data
            // and correct axes draws nothing. Opting out of the animation is
            // the supported workaround and costs only the fade-in.
            isAnimationActive={false}
            data={data}
            dataKey={valueKey}
            nameKey={nameKey}
            innerRadius={donut ? "55%" : 0}
            outerRadius="80%"
            paddingAngle={donut ? 2 : 0}
            label
          >
            {data.map((_, i) => (
              <Cell key={i} fill={props.series?.[i]?.color ?? DEFAULT_PALETTE[i % DEFAULT_PALETTE.length]} />
            ))}
          </Pie>
        </RePieChart>
      </ResponsiveContainer>
    </div>
  );
}
