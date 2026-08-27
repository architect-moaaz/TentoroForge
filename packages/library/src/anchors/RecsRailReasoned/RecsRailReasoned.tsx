"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * RecsRailReasoned — horizontal card rail with a *why* for each rec.
 * "Because you loved Sarah's Power Flow" → 3 classes to book. The reason is
 * as much the point as the recs; never render a rec without one.
 */
export const RecsRailReasonedProps = z.object({
  title: z.string().optional(),
  reason: z.string().optional(),          // the "why" — shown as section subtitle
  seeAllLabel: z.string().optional(),
  seeAllNavigate: z.string().optional(),
  items: z.array(z.object({
    title: z.string(),
    subtitle: z.string().optional(),
    meta: z.string().optional(),
    tag: z.string().optional(),           // "In stock", "2 left", "Waitlist"
    price: z.string().optional(),
    ctaLabel: z.string().optional(),
    ctaNavigate: z.string().optional(),
    accent: z.enum(["primary", "warning", "success"]).optional(),
  })).min(1).max(6).optional(),
});
export type RecsRailReasonedPropsType = z.infer<typeof RecsRailReasonedProps>;

const TAG_BG: Record<string, string> = {
  primary: "bg-primary/15 text-primary border-primary/40",
  warning: "bg-yellow-500/15 text-yellow-700 border-yellow-500/40",
  success: "bg-green-500/15 text-green-700 border-green-500/40",
};

type _RRR = NonNullable<RecsRailReasonedPropsType["items"]>[number];
export function RecsRailReasoned({ title, reason, seeAllLabel, seeAllNavigate, items }: RecsRailReasonedPropsType) {
  const cards: _RRR[] = items && items.length > 0 ? items : Array.from({ length: 3 }, () => ({ title: "" } as _RRR));
  return (
    <section data-anchor="recs_rail_reasoned" className="flex flex-col gap-3">
      <header className="flex items-baseline justify-between gap-4">
        <div className="flex flex-col gap-0.5">
          <h3
            className="text-lg font-medium tracking-tight text-foreground"
            style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
          >
            {title || <span className={skeleton("w-40")} />}
          </h3>
          {reason && <span className="text-xs text-muted-foreground">{reason}</span>}
        </div>
        {seeAllLabel && (
          <a href={seeAllNavigate || "#"} className="text-sm text-primary hover:brightness-110">
            {seeAllLabel} →
          </a>
        )}
      </header>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {cards.map((it, i) => (
          <article key={i} className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4 hover:border-primary/40 transition">
            {it.tag && (
              <span className={`self-start text-[10px] font-semibold uppercase tracking-widest border px-2 py-0.5 rounded-full ${TAG_BG[it.accent || "primary"]}`}>
                {it.tag}
              </span>
            )}
            <h4
              className="font-medium text-foreground leading-snug"
              style={{ fontFamily: "var(--typography-font-heading, inherit)", fontSize: "1.05rem" }}
            >
              {it.title || <span className={skeleton("w-32")} />}
            </h4>
            {it.subtitle && <span className="text-sm text-muted-foreground">{it.subtitle}</span>}
            {it.meta && <span className="text-xs text-muted-foreground">{it.meta}</span>}
            {(it.price || it.ctaLabel) && (
              <div className="flex items-center justify-between mt-1 pt-3 border-t border-dashed border-border">
                {it.price && <span className="text-xs text-muted-foreground">{it.price}</span>}
                {it.ctaLabel && (
                  <a
                    href={it.ctaNavigate || "#"}
                    className="text-xs font-medium h-8 px-3 inline-flex items-center rounded-full bg-primary text-primary-foreground hover:brightness-110"
                  >
                    {it.ctaLabel}
                  </a>
                )}
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
