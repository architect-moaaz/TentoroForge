"use client";

// packages/library/src/components/Chart/FunnelChart.tsx
import * as React from "react";
import { FunnelChart as ReFunnelChart, Funnel, LabelList, Tooltip, Cell, ResponsiveContainer } from "recharts";
import type { ChartPropsType } from "./Chart.schema";
import { useTokens } from "../../theme/tokens-context";

const DEFAULT_PALETTE = [
  "hsl(var(--primary))",
  "hsl(var(--accent))",
  "hsl(var(--success))",
  "hsl(var(--warning))",
  "hsl(var(--info))",
  "hsl(var(--destructive))",
];

/** Conversion funnel — each row is a stage: value = first series' dataKey
 *  (default "value"), label = xKey (default "label"). */
export function FunnelChartImpl(props: ChartPropsType) {
  const tokens = useTokens();
  const numericFamily = tokens.typography?.numeric?.family;
  const data = Array.isArray(props.data) ? props.data : [];
  const valueKey = props.series?.[0]?.dataKey ?? "value";
  const nameKey = props.xKey ?? "label";
  return (
    <div style={{ width: "100%", height: props.height ?? 240, fontFamily: numericFamily }}>
      <ResponsiveContainer>
        <ReFunnelChart>
          {props.showTooltip !== false && <Tooltip />}
          <Funnel dataKey={valueKey} nameKey={nameKey} data={data} isAnimationActive>
            <LabelList position="right" fill="var(--color-text-secondary)" stroke="none" dataKey={nameKey} fontSize={11} />
            {data.map((_, i) => (
              <Cell key={i} fill={props.series?.[i]?.color ?? DEFAULT_PALETTE[i % DEFAULT_PALETTE.length]} />
            ))}
          </Funnel>
        </ReFunnelChart>
      </ResponsiveContainer>
    </div>
  );
}
