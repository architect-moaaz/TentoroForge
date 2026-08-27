"use client";

// packages/library/src/components/Chart/BarChart.tsx
import * as React from "react";
import {
  BarChart as ReBarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { ChartPropsType } from "./Chart.schema";
import { useTokens } from "../../theme/tokens-context";

// Palette prefers the shadcn root tokens (--primary / --accent) so bar
// colors are the same swatches Badge, Tag, and Button use. The Tailwind
// numeric scale (--color-*-500) is a fallback for extra series beyond
// the two brand hues; --success and --warning give a distinct third and
// fourth colour without collapsing into the brand family.
const DEFAULT_PALETTE = [
  "hsl(var(--primary))",
  "hsl(var(--accent))",
  "hsl(var(--success))",
  "hsl(var(--warning))",
  "var(--color-primary-700, hsl(var(--primary) / 0.7))",
  "var(--color-accent-700,  hsl(var(--accent) / 0.7))",
];

export function BarChartImpl(props: ChartPropsType) {
  const tokens = useTokens();
  const numericFamily = tokens.typography?.numeric?.family;
  return (
    <div style={{ width: "100%", height: props.height ?? 240, fontFamily: numericFamily }}>
      <ResponsiveContainer>
        <ReBarChart data={Array.isArray(props.data) ? props.data : []}>
          {props.showGrid !== false && (
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
          )}
          <XAxis dataKey={props.xKey} stroke="var(--color-text-tertiary)" fontSize={11} />
          <YAxis stroke="var(--color-text-tertiary)" fontSize={11} />
          {props.showTooltip !== false && <Tooltip />}
          {props.showLegend !== false && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {props.series.map((s, i) => (
            <Bar
              // recharts 2.15's entry animation goes through react-smooth's
              // Animate, which does not survive React 19 — the series element
              // mounts but renders an EMPTY <g>, so a chart with correct data
              // and correct axes draws nothing. Opting out of the animation is
              // the supported workaround and costs only the fade-in.
              isAnimationActive={false}
              key={s.dataKey}
              dataKey={s.dataKey}
              name={s.name}
              fill={s.color ?? DEFAULT_PALETTE[i % DEFAULT_PALETTE.length]}
            />
          ))}
        </ReBarChart>
      </ResponsiveContainer>
    </div>
  );
}
