"use client";

// packages/library/src/components/Chart/RadarChart.tsx
import * as React from "react";
import {
  RadarChart as ReRadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  Radar, Legend, Tooltip, ResponsiveContainer,
} from "recharts";
import type { ChartPropsType } from "./Chart.schema";
import { useTokens } from "../../theme/tokens-context";

const DEFAULT_PALETTE = [
  "hsl(var(--primary))",
  "hsl(var(--accent))",
  "hsl(var(--success))",
  "hsl(var(--warning))",
];

/** Radar / spider — each row is an axis (label = xKey, default "subject"); each
 *  series is a ring. For competency maps, skill maps, multi-dimension scoring. */
export function RadarChartImpl(props: ChartPropsType) {
  const tokens = useTokens();
  const numericFamily = tokens.typography?.numeric?.family;
  const data = Array.isArray(props.data) ? props.data : [];
  const axisKey = props.xKey ?? "subject";
  return (
    <div style={{ width: "100%", height: props.height ?? 260, fontFamily: numericFamily }}>
      <ResponsiveContainer>
        <ReRadarChart data={data}>
          <PolarGrid stroke="var(--color-border-default)" />
          <PolarAngleAxis dataKey={axisKey} tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }} />
          <PolarRadiusAxis tick={{ fontSize: 10, fill: "var(--color-text-tertiary)" }} />
          {props.showTooltip !== false && <Tooltip />}
          {props.showLegend !== false && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {props.series.map((s, i) => (
            <Radar
              // recharts 2.15's entry animation goes through react-smooth's
              // Animate, which does not survive React 19 — the series element
              // mounts but renders an EMPTY <g>, so a chart with correct data
              // and correct axes draws nothing. Opting out of the animation is
              // the supported workaround and costs only the fade-in.
              isAnimationActive={false}
              key={s.dataKey}
              name={s.name}
              dataKey={s.dataKey}
              stroke={s.color ?? DEFAULT_PALETTE[i % DEFAULT_PALETTE.length]}
              fill={s.color ?? DEFAULT_PALETTE[i % DEFAULT_PALETTE.length]}
              fillOpacity={0.35}
            />
          ))}
        </ReRadarChart>
      </ResponsiveContainer>
    </div>
  );
}
