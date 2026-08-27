"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * ShiftMetricsRail — shift-summary strip: what's happened this shift.
 * Distinct from SlaVitalsStrip: those are current-state SLAs, these are
 * cumulative counts (handled / resolved / escalated / avg time).
 */
export const ShiftMetricsRailProps = z.object({
  title: z.string().optional(),
  shiftLabel: z.string().optional(),         // "Day shift · 6h in"
  metrics: z.array(z.object({
    label: z.string(),
    value: z.union([z.string(), z.number()]),
    unit: z.string().optional(),
    hint: z.string().optional(),             // "vs 42 last shift"
  })).min(1).max(6).optional(),
});
export type ShiftMetricsRailPropsType = z.infer<typeof ShiftMetricsRailProps>;

type _SMR = NonNullable<ShiftMetricsRailPropsType["metrics"]>[number];
export function ShiftMetricsRail({ title, shiftLabel, metrics }: ShiftMetricsRailPropsType) {
  const items: _SMR[] = metrics && metrics.length > 0 ? metrics : Array.from({ length: 4 }, () => ({ label: "", value: "" } as _SMR));
  return (
    <section
      data-anchor="shift_metrics_rail"
      className="rounded-xl border border-border bg-card px-5 py-4"
    >
      <header className="flex items-baseline justify-between mb-3">
        <h3
          className="text-sm font-semibold tracking-tight text-foreground"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          {title || "This shift"}
        </h3>
        {shiftLabel && <span className="text-[11px] text-muted-foreground tabular-nums">{shiftLabel}</span>}
      </header>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {items.map((m, i) => (
          <div key={i} className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              {m.label || <span className={skeleton("w-16")} />}
            </span>
            <div className="flex items-baseline gap-1">
              <span
                className="text-2xl font-semibold tracking-tight tabular-nums text-foreground leading-none"
                style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
              >
                {String(m.value) || <span className={skeleton("w-8")} />}
              </span>
              {m.unit && <span className="text-xs text-muted-foreground">{m.unit}</span>}
            </div>
            {m.hint && <span className="text-[10px] text-muted-foreground leading-tight">{m.hint}</span>}
          </div>
        ))}
      </div>
    </section>
  );
}
