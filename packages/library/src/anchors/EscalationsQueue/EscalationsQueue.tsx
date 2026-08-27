"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * EscalationsQueue — the manager's "who needs me" list. Not a full inbox —
 * items that were surfaced BECAUSE they need a decision or unblock. Each
 * row: who escalated it, what they need, how long it's been waiting.
 */
export const EscalationsQueueProps = z.object({
  title: z.string().optional(),
  seeAllLabel: z.string().optional(),
  seeAllNavigate: z.string().optional(),
  items: z.array(z.object({
    from: z.string(),
    ask: z.string(),
    context: z.string().optional(),
    waiting: z.string().optional(),     // "2h", "1d"
    severity: z.enum(["urgent", "normal"]).optional(),
    navigate: z.string().optional(),
  })).min(1).max(6).optional(),
});
export type EscalationsQueuePropsType = z.infer<typeof EscalationsQueueProps>;

type _EQ = NonNullable<EscalationsQueuePropsType["items"]>[number];
export function EscalationsQueue({ title, seeAllLabel, seeAllNavigate, items }: EscalationsQueuePropsType) {
  const rows: _EQ[] = items && items.length > 0 ? items : Array.from({ length: 3 }, () => ({ from: "", ask: "" } as _EQ));
  return (
    <section
      data-anchor="escalations_queue"
      className="rounded-xl border border-border bg-card overflow-hidden"
    >
      <header className="flex items-baseline justify-between px-5 py-3 border-b border-border">
        <h3
          className="text-sm font-semibold tracking-tight text-foreground"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          {title || "Waiting on you"}
        </h3>
        {seeAllLabel && (
          <a href={seeAllNavigate || "#"} className="text-xs text-primary hover:brightness-110">
            {seeAllLabel} →
          </a>
        )}
      </header>
      <ul className="divide-y divide-border">
        {rows.map((r, i) => (
          <li key={i}>
            <a
              href={r.navigate || "#"}
              className="grid grid-cols-[auto_1fr_auto] items-start gap-3 px-5 py-3 hover:bg-accent/40 transition"
            >
              <span
                className="mt-0.5 shrink-0 h-8 w-8 rounded-full grid place-items-center text-[10px] font-semibold text-primary-foreground"
                style={{ background: r.severity === "urgent" ? "var(--color-primary)" : "color-mix(in oklch, var(--color-primary) 60%, transparent)" }}
                aria-hidden="true"
              >
                {r.from ? r.from.split(" ").map((s: string) => s[0]).slice(0, 2).join("").toUpperCase() : ""}
              </span>
              <div className="flex flex-col gap-0.5 min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-medium text-foreground truncate">
                    {r.from || <span className={skeleton("w-24")} />}
                  </span>
                  {r.severity === "urgent" && (
                    <span className="text-[9px] font-bold uppercase tracking-wider text-red-700 bg-red-500/15 border border-red-500/40 px-1 py-0 rounded">
                      URGENT
                    </span>
                  )}
                </div>
                <span className="text-sm text-foreground leading-snug">
                  {r.ask || <span className={skeleton("w-40")} />}
                </span>
                {r.context && (
                  <span className="text-xs text-muted-foreground truncate">{r.context}</span>
                )}
              </div>
              {r.waiting && (
                <span className="text-[11px] text-muted-foreground tabular-nums self-start mt-1">{r.waiting}</span>
              )}
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
