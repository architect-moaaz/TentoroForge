"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * LiveEventLog — the ops-console stream: newest first, monospaced-adjacent,
 * dense. Each row is a timestamped event with actor, verb, target. Optional
 * severity dot on the left, click-through on the row.
 */
export const LiveEventLogProps = z.object({
  title: z.string().optional(),
  seeAllLabel: z.string().optional(),
  seeAllNavigate: z.string().optional(),
  events: z.array(z.object({
    time: z.string(),                     // "14:03:22"
    actor: z.string().optional(),
    verb: z.string(),
    target: z.string().optional(),
    severity: z.enum(["ok", "warn", "err"]).optional(),
    navigate: z.string().optional(),
  })).min(1).max(20).optional(),
});
export type LiveEventLogPropsType = z.infer<typeof LiveEventLogProps>;

const DOT: Record<string, string> = {
  ok:   "bg-green-500",
  warn: "bg-yellow-500",
  err:  "bg-red-500",
};

type _LEL = NonNullable<LiveEventLogPropsType["events"]>[number];
export function LiveEventLog({ title, seeAllLabel, seeAllNavigate, events }: LiveEventLogPropsType) {
  const rows: _LEL[] = events && events.length > 0 ? events : Array.from({ length: 6 }, () => ({ time: "", verb: "" } as _LEL));
  return (
    <section
      data-anchor="live_event_log"
      className="rounded-xl border border-border bg-card overflow-hidden"
    >
      <header className="flex items-baseline justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-500 opacity-60" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
          </span>
          <h3
            className="text-sm font-semibold tracking-tight text-foreground"
            style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
          >
            {title || "Live events"}
          </h3>
        </div>
        {seeAllLabel && (
          <a href={seeAllNavigate || "#"} className="text-xs text-primary hover:brightness-110">
            {seeAllLabel} →
          </a>
        )}
      </header>
      <ol className="divide-y divide-border max-h-96 overflow-y-auto">
        {rows.map((e, i) => (
          <li key={i} className="grid grid-cols-[8ch_8px_1fr] gap-3 items-center px-4 py-2 hover:bg-accent/40 transition">
            <span className="text-[11px] text-muted-foreground tabular-nums font-mono">
              {e.time || <span className={skeleton("w-full")} />}
            </span>
            <span className={`h-2 w-2 rounded-full ${DOT[e.severity || "ok"]}`} aria-hidden="true" />
            <a
              href={e.navigate || "#"}
              className="text-[13px] text-foreground truncate leading-tight"
            >
              {e.actor && <span className="font-medium">{e.actor} </span>}
              <span className="text-muted-foreground">{e.verb || <span className={skeleton("w-24")} />}</span>
              {e.target && <span className="ml-1 font-medium">{e.target}</span>}
            </a>
          </li>
        ))}
      </ol>
    </section>
  );
}
