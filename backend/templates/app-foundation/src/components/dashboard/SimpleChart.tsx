"use client";

import { cn } from "@/lib/utils";

interface SimpleBarChartProps {
  data: { label: string; value: number; color?: string }[];
  height?: number;
  className?: string;
}

/**
 * Lightweight bar chart — no external dependencies.
 * For full charts, add recharts to package.json and use BarChart/LineChart directly.
 */
export function SimpleBarChart({ data, height = 200, className }: SimpleBarChartProps) {
  const max = Math.max(...data.map((d) => d.value), 1);

  return (
    <div className={cn("flex items-end gap-2", className)} style={{ height }}>
      {data.map((item, i) => (
        <div key={i} className="flex-1 flex flex-col items-center gap-1">
          <span className="text-xs font-medium text-foreground">{item.value}</span>
          <div
            className="w-full rounded-t-md transition-all duration-300"
            style={{
              height: `${(item.value / max) * 100}%`,
              minHeight: 4,
              backgroundColor: item.color || "hsl(var(--primary))",
            }}
          />
          <span className="text-[10px] text-muted-foreground truncate w-full text-center">{item.label}</span>
        </div>
      ))}
    </div>
  );
}

interface SimpleDonutProps {
  value: number;
  max?: number;
  size?: number;
  label?: string;
  color?: string;
  className?: string;
}

export function SimpleDonut({ value, max = 100, size = 80, label, color, className }: SimpleDonutProps) {
  const pct = Math.min(100, (value / max) * 100);
  const r = (size - 8) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (pct / 100) * circ;

  return (
    <div className={cn("flex flex-col items-center gap-1", className)}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="hsl(var(--muted))" strokeWidth={6} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color || "hsl(var(--primary))"} strokeWidth={6} strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round" className="transition-all duration-500" />
      </svg>
      {label && <span className="text-xs text-muted-foreground">{label}</span>}
    </div>
  );
}
