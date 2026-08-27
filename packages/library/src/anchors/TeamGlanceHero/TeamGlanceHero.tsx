"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * TeamGlanceHero — the manager's "how's the team" hero. Opens with the
 * team's state, not the manager's queue. Headline metric + 3-4 vitals
 * about the group (headcount, health, momentum) with narrative color.
 */
export const TeamGlanceHeroProps = z.object({
  eyebrow: z.string().optional(),          // "This week"
  headline: z.string().optional(),         // "Sales team · 12 people"
  narrative: z.string().optional(),        // "3 wins, 2 blockers, hitting 87% of plan"
  vitals: z.array(z.object({
    label: z.string(),
    value: z.union([z.string(), z.number()]),
    unit: z.string().optional(),
    trend: z.enum(["up", "down", "flat"]).optional(),
  })).min(1).max(4).optional(),
});
export type TeamGlanceHeroPropsType = z.infer<typeof TeamGlanceHeroProps>;

const TREND: Record<string, string> = { up: "text-green-600", down: "text-red-600", flat: "text-muted-foreground" };
const ARROW: Record<string, string> = { up: "↑", down: "↓", flat: "→" };

type _TGH = NonNullable<TeamGlanceHeroPropsType["vitals"]>[number];
export function TeamGlanceHero({ eyebrow, headline, narrative, vitals }: TeamGlanceHeroPropsType) {
  const items: _TGH[] = vitals && vitals.length > 0 ? vitals : Array.from({ length: 3 }, () => ({ label: "", value: "" } as _TGH));
  return (
    <section
      data-anchor="team_glance_hero"
      className="rounded-2xl border border-border bg-card p-6 md:p-8 flex flex-col gap-5"
    >
      <div className="flex flex-col gap-2">
        {eyebrow && (
          <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">{eyebrow}</span>
        )}
        <h2
          className="text-2xl md:text-3xl font-medium tracking-tight text-foreground"
          style={{ fontFamily: "var(--typography-font-heading, inherit)", textWrap: "balance" as any }}
        >
          {headline || <span className={skeleton("w-56")} />}
        </h2>
        {narrative && (
          <p className="text-sm md:text-base text-muted-foreground leading-relaxed max-w-prose">{narrative}</p>
        )}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 border-t border-border pt-4">
        {items.map((v, i) => (
          <div key={i} className="flex flex-col gap-0.5">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              {v.label || <span className={skeleton("w-16")} />}
            </span>
            <div className="flex items-baseline gap-1">
              <span
                className="text-xl font-semibold tabular-nums text-foreground leading-none"
                style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
              >
                {String(v.value) || <span className={skeleton("w-8")} />}
              </span>
              {v.unit && <span className="text-xs text-muted-foreground">{v.unit}</span>}
              {v.trend && <span className={`text-xs ${TREND[v.trend]}`} aria-hidden="true">{ARROW[v.trend]}</span>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
