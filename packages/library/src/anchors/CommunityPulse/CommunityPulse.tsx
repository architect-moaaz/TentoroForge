"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * CommunityPulse — activity feed / studio pulse. What other members are
 * doing right now. Studio announcements. Milestones. The one section that
 * makes a member feel part of a place rather than transacting alone.
 */
export const CommunityPulseProps = z.object({
  title: z.string().optional(),
  seeAllLabel: z.string().optional(),
  seeAllNavigate: z.string().optional(),
  items: z.array(z.object({
    initials: z.string().optional(),
    body: z.string(),
    time: z.string().optional(),
    highlight: z.string().optional(),
  })).min(1).max(6).optional(),
});
export type CommunityPulsePropsType = z.infer<typeof CommunityPulseProps>;

type _CP = NonNullable<CommunityPulsePropsType["items"]>[number];
export function CommunityPulse({ title, seeAllLabel, seeAllNavigate, items }: CommunityPulsePropsType) {
  const rows: _CP[] = items && items.length > 0 ? items : Array.from({ length: 3 }, () => ({ body: "" } as _CP));
  return (
    <section
      data-anchor="community_pulse"
      className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6"
    >
      <header className="flex items-baseline justify-between">
        <h3
          className="text-lg font-medium tracking-tight text-foreground"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          {title || "Community pulse"}
        </h3>
        {seeAllLabel && (
          <a href={seeAllNavigate || "#"} className="text-sm text-primary hover:brightness-110">
            {seeAllLabel} →
          </a>
        )}
      </header>
      <ul className="flex flex-col gap-4">
        {rows.map((r, i) => (
          <li key={i} className="flex items-start gap-3 pb-4 border-b border-border last:border-b-0 last:pb-0">
            <span
              className="shrink-0 h-8 w-8 rounded-full grid place-items-center text-[11px] font-semibold text-primary-foreground"
              style={{ background: "linear-gradient(135deg, var(--color-primary), var(--color-primary, #6b7280))" }}
              aria-hidden="true"
            >
              {r.initials || (r.body ? (r.body[0] || "•").toUpperCase() : "")}
            </span>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-foreground leading-relaxed">
                {r.body || <span className={skeleton("w-full max-w-md")} />}
                {r.highlight && (
                  <span
                    className="ml-1 italic text-primary"
                    style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
                  >
                    {r.highlight}
                  </span>
                )}
              </p>
              {r.time && <span className="text-xs text-muted-foreground mt-1 block">{r.time}</span>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
