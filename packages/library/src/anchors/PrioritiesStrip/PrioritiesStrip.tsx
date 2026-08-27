"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * PrioritiesStrip — the manager's top 3-5 priorities today. Each has an
 * owner name, a due signal, and a status chip. Not a task list — a
 * curated set of what needs their attention, promoted from the noise.
 */
export const PrioritiesStripProps = z.object({
  title: z.string().optional(),
  items: z.array(z.object({
    label: z.string(),
    owner: z.string().optional(),
    due: z.string().optional(),               // "Today", "2d", "Overdue"
    status: z.enum(["on_track", "at_risk", "blocked"]).optional(),
    navigate: z.string().optional(),
  })).min(1).max(5).optional(),
});
export type PrioritiesStripPropsType = z.infer<typeof PrioritiesStripProps>;

const STATUS: Record<string, string> = {
  on_track: "bg-green-500/15 text-green-700 border-green-500/40",
  at_risk:  "bg-yellow-500/15 text-yellow-700 border-yellow-500/40",
  blocked:  "bg-red-500/15 text-red-700 border-red-500/40",
};

type _PS = NonNullable<PrioritiesStripPropsType["items"]>[number];
export function PrioritiesStrip({ title, items }: PrioritiesStripPropsType) {
  const rows: _PS[] = items && items.length > 0 ? items : Array.from({ length: 3 }, () => ({ label: "" } as _PS));
  return (
    <section
      data-anchor="priorities_strip"
      className="rounded-xl border border-border bg-card px-5 py-4"
    >
      <header className="flex items-baseline justify-between mb-3">
        <h3
          className="text-sm font-semibold tracking-tight text-foreground"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          {title || "Priorities"}
        </h3>
        <span className="text-[10px] text-muted-foreground tabular-nums">{rows.length}</span>
      </header>
      <ol className="flex flex-col gap-2">
        {rows.map((p, i) => (
          <li key={i}>
            <a
              href={p.navigate || "#"}
              className="grid grid-cols-[auto_1fr_auto_auto] items-center gap-3 rounded-lg border border-border bg-background px-3 py-2 hover:border-primary/40 transition"
            >
              <span
                className="h-6 w-6 rounded-full grid place-items-center text-[11px] font-semibold text-primary bg-primary/10"
                aria-hidden="true"
              >
                {i + 1}
              </span>
              <span className="text-sm font-medium text-foreground truncate">
                {p.label || <span className={skeleton("w-40")} />}
              </span>
              {p.owner && <span className="text-xs text-muted-foreground truncate">{p.owner}</span>}
              <div className="flex items-center gap-2">
                {p.due && <span className="text-[10px] font-medium text-muted-foreground tabular-nums">{p.due}</span>}
                {p.status && (
                  <span className={`text-[9px] font-bold uppercase tracking-wider border px-1.5 py-0.5 rounded ${STATUS[p.status]}`}>
                    {p.status.replace("_", " ")}
                  </span>
                )}
              </div>
            </a>
          </li>
        ))}
      </ol>
    </section>
  );
}
