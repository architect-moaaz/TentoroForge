"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * CalendarWeek — 7-day strip with per-day event count. Not a full calendar,
 * a compact "what's the week look like" scan bar. Each day tile shows date,
 * event count, and a subtle density indicator.
 */
export const CalendarWeekProps = z.object({
  title: z.string().optional(),
  seeAllLabel: z.string().optional(),
  seeAllNavigate: z.string().optional(),
  days: z.array(z.object({
    weekday: z.string(),         // "Mon"
    date: z.string(),            // "18"
    eventCount: z.number().int().nonnegative().optional(),
    highlight: z.string().optional(),  // "Board", "1:1s"
    today: z.boolean().optional(),
    navigate: z.string().optional(),
  })).min(1).max(14).optional(),
});
export type CalendarWeekPropsType = z.infer<typeof CalendarWeekProps>;

type _CW = NonNullable<CalendarWeekPropsType["days"]>[number];
export function CalendarWeek({ title, seeAllLabel, seeAllNavigate, days }: CalendarWeekPropsType) {
  const items: _CW[] = days && days.length > 0
    ? days
    : Array.from({ length: 7 }, () => ({ weekday: "", date: "" } as _CW));
  return (
    <section data-anchor="calendar_week" className="flex flex-col gap-3">
      <header className="flex items-baseline justify-between">
        <h3
          className="text-lg font-medium tracking-tight text-foreground"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          {title || "This week"}
        </h3>
        {seeAllLabel && (
          <a href={seeAllNavigate || "#"} className="text-sm text-primary hover:brightness-110">
            {seeAllLabel} →
          </a>
        )}
      </header>
      <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${Math.min(items.length, 7)}, minmax(0, 1fr))` }}>
        {items.slice(0, 7).map((d, i) => {
          const count = typeof d.eventCount === "number" ? d.eventCount : 0;
          const density = count === 0 ? 0 : count <= 2 ? 1 : count <= 5 ? 2 : 3;
          return (
            <a
              key={i}
              href={d.navigate || "#"}
              className={`flex flex-col items-stretch gap-1 rounded-xl border p-3 transition min-h-[100px] ${
                d.today
                  ? "bg-primary text-primary-foreground border-primary shadow-sm"
                  : "bg-card border-border text-foreground hover:bg-accent"
              }`}
            >
              <div className="flex items-baseline justify-between">
                <span className={`text-[10px] font-semibold uppercase tracking-widest ${d.today ? "opacity-85" : "text-muted-foreground"}`}>
                  {d.weekday || <span className={skeleton("w-8")} />}
                </span>
                {d.today && <span className="text-[9px] font-bold uppercase tracking-wider">Today</span>}
              </div>
              <span
                className="text-2xl font-medium tabular-nums tracking-tight leading-none"
                style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
              >
                {d.date || <span className={skeleton("w-6")} />}
              </span>
              <div className="mt-auto flex items-center gap-1" aria-hidden="true">
                {[1, 2, 3].map((n) => (
                  <span
                    key={n}
                    className={`h-1 flex-1 rounded-full ${
                      density >= n
                        ? d.today ? "bg-white/70" : "bg-primary"
                        : d.today ? "bg-white/20" : "bg-border"
                    }`}
                  />
                ))}
              </div>
              {d.highlight ? (
                <span className={`text-[10px] truncate ${d.today ? "opacity-90" : "text-muted-foreground"}`}>
                  {d.highlight}
                </span>
              ) : (
                <span className={`text-[10px] ${d.today ? "opacity-90" : "text-muted-foreground"} tabular-nums`}>
                  {count} event{count === 1 ? "" : "s"}
                </span>
              )}
            </a>
          );
        })}
      </div>
    </section>
  );
}
