// packages/library/src/components/Sparkline/Sparkline.tsx
import * as React from "react";
import type { SparklinePropsType } from "./Sparkline.schema";

export interface SparklineProps extends SparklinePropsType {}

/**
 * Inline mini-chart — just the shape, no axes, no tooltips.
 * Use inside DataGrid cells, MetricTile trends, dashboard rows.
 */
export function Sparkline({
  data, width = 100, height = 24, color = "currentColor", showDots = false,
}: SparklineProps) {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 2) - 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" points={points.join(" ")} />
      {showDots && data.map((v, i) => {
        const x = (i / (data.length - 1)) * width;
        const y = height - ((v - min) / range) * (height - 2) - 1;
        return <circle key={i} cx={x} cy={y} r="1.5" fill={color} />;
      })}
    </svg>
  );
}
