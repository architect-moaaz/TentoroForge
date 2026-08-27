"use client";

// packages/library/src/components/Chart/AreaChart.tsx
import * as React from "react";
import {
  AreaChart as ReAreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { ChartPropsType } from "./Chart.schema";
import { useTokens } from "../../theme/tokens-context";

const DEFAULT_PALETTE = [
  "hsl(var(--primary))",
  "hsl(var(--accent))",
  "hsl(var(--success))",
  "hsl(var(--warning))",
  "var(--color-primary-700, hsl(var(--primary) / 0.7))",
  "var(--color-accent-700,  hsl(var(--accent) / 0.7))",
];

export function AreaChartImpl(props: ChartPropsType) {
  const tokens = useTokens();
  const numericFamily = tokens.typography?.numeric?.family;
  return (
    <div style={{ width: "100%", height: props.height ?? 240, fontFamily: numericFamily }}>
      <ResponsiveContainer>
        <ReAreaChart data={Array.isArray(props.data) ? props.data : []}>
          {props.showGrid !== false && (
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
          )}
          <XAxis dataKey={props.xKey} stroke="var(--color-text-tertiary)" fontSize={11} />
          <YAxis stroke="var(--color-text-tertiary)" fontSize={11} />
          {props.showTooltip !== false && <Tooltip />}
          {props.showLegend !== false && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {props.series.map((s, i) => {
            const color = s.color ?? DEFAULT_PALETTE[i % DEFAULT_PALETTE.length];
            return (
              <Area
                // recharts 2.15's entry animation goes through react-smooth's
                // Animate, which does not survive React 19 — the series element
                // mounts but renders an EMPTY <g>, so a chart with correct data
                // and correct axes draws nothing. Opting out of the animation is
                // the supported workaround and costs only the fade-in.
                isAnimationActive={false}
                key={s.dataKey}
                type="monotone"
                dataKey={s.dataKey}
                name={s.name}
                stroke={color}
                strokeWidth={2}
                fill={color}
                fillOpacity={0.3}
              />
            );
          })}
        </ReAreaChart>
      </ResponsiveContainer>
    </div>
  );
}
