"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * SlaVitalsStrip — ops-console vitals: numeric-heavy strip with target vs
 * actual per SLA and a compact trend arrow. Tabular numerals, colored
 * deltas, no chartjunk.
 */
export const SlaVitalsStripProps = z.object({
  tiles: z.array(z.object({
    label: z.string(),
    value: z.union([z.string(), z.number()]),
    unit: z.string().optional(),          // "s", "%", "ms"
    target: z.string().optional(),        // "≤ 30s"
    delta: z.string().optional(),         // "-4s", "+2%"
    status: z.enum(["ok", "watch", "breach"]).optional(),
  })).min(1).max(6).optional(),
});
export type SlaVitalsStripPropsType = z.infer<typeof SlaVitalsStripProps>;

const STATUS: Record<string, { chip: string; delta: string }> = {
  ok:     { chip: "bg-green-500/15 text-green-700 border-green-500/40",   delta: "text-green-600" },
  watch:  { chip: "bg-yellow-500/15 text-yellow-700 border-yellow-500/40", delta: "text-yellow-600" },
  breach: { chip: "bg-red-500/15 text-red-700 border-red-500/40",         delta: "text-red-600" },
};

export function SlaVitalsStrip({ tiles }: SlaVitalsStripPropsType) {
  const items = tiles && tiles.length > 0 ? tiles : [{ label: "", value: "" }, { label: "", value: "" }, { label: "", value: "" }, { label: "", value: "" }];
  const cols = items.length <= 3 ? "grid-cols-1 sm:grid-cols-3" : "grid-cols-2 md:grid-cols-4 lg:grid-cols-6";
  return (
    <section data-anchor="sla_vitals_strip" className={`grid ${cols} gap-2`}>
      {items.map((t, i) => {
        const st = STATUS[t.status || "ok"];
        return (
          <div key={i} className="flex flex-col gap-1 rounded-lg border border-border bg-card px-3 py-3">
            <div className="flex items-start justify-between gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground truncate">
                {t.label || <span className={skeleton("w-14")} />}
              </span>
              {t.status && (
                <span className={`text-[9px] font-bold uppercase border px-1 py-0 rounded ${st.chip}`}>
                  {t.status.toUpperCase()}
                </span>
              )}
            </div>
            <div className="flex items-baseline gap-1">
              <span
                className="text-2xl font-semibold tracking-tight tabular-nums text-foreground leading-none"
                style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
              >
                {String(t.value) || <span className={skeleton("w-10")} />}
              </span>
              {t.unit && <span className="text-xs text-muted-foreground">{t.unit}</span>}
            </div>
            <div className="flex items-baseline justify-between text-[10px] text-muted-foreground tabular-nums leading-tight">
              {t.target && <span>vs {t.target}</span>}
              {t.delta && <span className={st.delta}>{t.delta}</span>}
            </div>
          </div>
        );
      })}
    </section>
  );
}
