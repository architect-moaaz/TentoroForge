"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * TeamStatusBoard — grid of team-member tiles showing current state, active
 * assignment, and load. Ops-console: an operator can see at a glance who
 * is free, who is on a call, who is over capacity.
 */
export const TeamStatusBoardProps = z.object({
  title: z.string().optional(),
  members: z.array(z.object({
    name: z.string(),
    role: z.string().optional(),
    state: z.enum(["available", "busy", "away", "offline"]).optional(),
    task: z.string().optional(),
    load: z.number().min(0).max(100).optional(),   // 0-100 utilisation
  })).min(1).max(24).optional(),
});
export type TeamStatusBoardPropsType = z.infer<typeof TeamStatusBoardProps>;

const STATE: Record<string, { chip: string; ring: string; label: string }> = {
  available: { chip: "bg-green-500/15 text-green-700",   ring: "ring-green-500",   label: "Available" },
  busy:      { chip: "bg-red-500/15 text-red-700",       ring: "ring-red-500",     label: "Busy" },
  away:      { chip: "bg-yellow-500/15 text-yellow-700", ring: "ring-yellow-500",  label: "Away" },
  offline:   { chip: "bg-muted text-muted-foreground",   ring: "ring-muted",       label: "Offline" },
};

type _TSB = NonNullable<TeamStatusBoardPropsType["members"]>[number];
export function TeamStatusBoard({ title, members }: TeamStatusBoardPropsType) {
  const rows: _TSB[] = members && members.length > 0 ? members : Array.from({ length: 6 }, () => ({ name: "", state: "offline" } as _TSB));
  return (
    <section
      data-anchor="team_status_board"
      className="rounded-xl border border-border bg-card overflow-hidden"
    >
      <header className="flex items-baseline justify-between px-5 py-3 border-b border-border">
        <h3
          className="text-sm font-semibold tracking-tight text-foreground"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          {title || "Team"}
        </h3>
        <span className="text-xs text-muted-foreground tabular-nums">
          {rows.filter(m => m.state === "available").length}/{rows.length} available
        </span>
      </header>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 p-4">
        {rows.map((m, i) => {
          const st = STATE[m.state || "offline"];
          const initials = m.name ? m.name.split(" ").map(s => s[0]).slice(0, 2).join("").toUpperCase() : "";
          return (
            <div key={i} className="flex items-start gap-3 rounded-lg border border-border p-3 bg-background">
              <span
                className={`shrink-0 h-9 w-9 rounded-full grid place-items-center text-[11px] font-semibold text-primary-foreground ring-2 ${st.ring} ring-offset-2 ring-offset-background`}
                style={{ background: "linear-gradient(135deg, var(--color-primary), var(--color-primary))" }}
                aria-hidden="true"
              >
                {initials || "·"}
              </span>
              <div className="flex-1 min-w-0 flex flex-col gap-0.5">
                <span className="text-sm font-medium text-foreground truncate leading-tight">
                  {m.name || <span className={skeleton("w-20")} />}
                </span>
                {m.role && <span className="text-[10px] text-muted-foreground truncate">{m.role}</span>}
                <div className="flex items-center gap-2 mt-1">
                  <span className={`text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${st.chip}`}>
                    {st.label}
                  </span>
                  {typeof m.load === "number" && (
                    <span className="text-[10px] text-muted-foreground tabular-nums">{m.load}%</span>
                  )}
                </div>
                {m.task && <span className="text-[11px] text-muted-foreground truncate mt-1">{m.task}</span>}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
