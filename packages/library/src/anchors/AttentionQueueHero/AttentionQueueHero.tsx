"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * AttentionQueueHero — the ops-console top card. Not a welcome hero: an
 * urgent list. "3 alerts, 2 escalations, 1 SLA breach" — the operator's
 * next actions summarized above the fold, with severity encoded in the
 * severity stripe (not just color).
 */
export const AttentionQueueHeroProps = z.object({
  eyebrow: z.string().optional(),        // "Now"
  headline: z.string().optional(),       // "3 items need you"
  items: z.array(z.object({
    severity: z.enum(["critical", "warning", "info"]).optional(),
    label: z.string(),
    detail: z.string().optional(),
    ago: z.string().optional(),           // "3m ago"
    ctaLabel: z.string().optional(),
    ctaNavigate: z.string().optional(),
  })).min(1).max(6).optional(),
});
export type AttentionQueueHeroPropsType = z.infer<typeof AttentionQueueHeroProps>;

const SEVERITY: Record<string, { bar: string; chip: string; label: string }> = {
  critical: { bar: "bg-red-500",    chip: "bg-red-500/15 text-red-700 border-red-500/40",       label: "CRITICAL" },
  warning:  { bar: "bg-yellow-500", chip: "bg-yellow-500/15 text-yellow-700 border-yellow-500/40", label: "WARN" },
  info:     { bar: "bg-primary",    chip: "bg-primary/15 text-primary border-primary/40",       label: "INFO" },
};

type _AQH = NonNullable<AttentionQueueHeroPropsType["items"]>[number];
export function AttentionQueueHero(props: AttentionQueueHeroPropsType) {
  const { eyebrow, headline, items } = props;
  const rows: _AQH[] = items && items.length > 0 ? items : Array.from({ length: 3 }, () => ({ severity: "info", label: "" } as _AQH));
  return (
    <section
      data-anchor="attention_queue_hero"
      className="rounded-xl border border-border bg-card overflow-hidden"
    >
      <header className="flex items-baseline justify-between gap-3 px-6 pt-5 pb-3 border-b border-border">
        <div className="flex items-baseline gap-3">
          {eyebrow && (
            <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">
              {eyebrow}
            </span>
          )}
          <h2
            className="text-xl font-semibold tracking-tight text-foreground"
            style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
          >
            {headline || <span className={skeleton("w-40")} />}
          </h2>
        </div>
        <span className="text-xs text-muted-foreground tabular-nums">{rows.length} item{rows.length === 1 ? "" : "s"}</span>
      </header>
      <ul>
        {rows.map((r, i) => {
          const sev = SEVERITY[r.severity || "info"];
          return (
            <li
              key={i}
              className="grid grid-cols-[4px_1fr_auto] items-center gap-4 pr-6 border-b border-border last:border-b-0 hover:bg-accent/50 transition"
            >
              <span className={`self-stretch ${sev.bar}`} aria-hidden="true" />
              <div className="flex flex-col gap-0.5 py-3 min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className={`text-[9px] font-bold uppercase tracking-widest border px-1.5 py-0.5 rounded ${sev.chip}`}>
                    {sev.label}
                  </span>
                  <span className="text-sm font-medium text-foreground truncate">
                    {r.label || <span className={skeleton("w-40")} />}
                  </span>
                </div>
                {r.detail && <span className="text-xs text-muted-foreground truncate">{r.detail}</span>}
              </div>
              <div className="flex items-center gap-3 py-3">
                {r.ago && <span className="text-xs text-muted-foreground tabular-nums">{r.ago}</span>}
                {r.ctaLabel && (
                  <a
                    href={r.ctaNavigate || "#"}
                    className="text-xs font-medium h-8 px-3 inline-flex items-center rounded bg-foreground text-background hover:opacity-90"
                  >
                    {r.ctaLabel}
                  </a>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
