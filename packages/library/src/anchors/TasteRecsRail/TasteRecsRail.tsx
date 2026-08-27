"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * TasteRecsRail — personalized recs with the *why* attached ("Because you
 * bought Loop Hobo"). Similar layout to TrendingRail but with a mandatory
 * personalization reason at the top of each card.
 */
export const TasteRecsRailProps = z.object({
  title: z.string().optional(),
  reason: z.string().optional(),  // section-level why
  seeAllLabel: z.string().optional(),
  seeAllNavigate: z.string().optional(),
  items: z.array(z.object({
    imageSrc: z.string().optional(),
    title: z.string(),
    subtitle: z.string().optional(),
    price: z.string().optional(),
    matchReason: z.string().optional(),  // per-item reason
    navigate: z.string().optional(),
  })).min(1).max(6).optional(),
});
export type TasteRecsRailPropsType = z.infer<typeof TasteRecsRailProps>;

type _TRR = NonNullable<TasteRecsRailPropsType["items"]>[number];
export function TasteRecsRail({ title, reason, seeAllLabel, seeAllNavigate, items }: TasteRecsRailPropsType) {
  const cards: _TRR[] = items && items.length > 0 ? items : Array.from({ length: 3 }, () => ({ title: "" } as _TRR));
  return (
    <section data-anchor="taste_recs_rail" className="flex flex-col gap-3">
      <header className="flex items-baseline justify-between gap-4">
        <div className="flex flex-col gap-0.5">
          <h3
            className="text-lg font-medium tracking-tight text-foreground"
            style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
          >
            {title || "Picked for you"}
          </h3>
          {reason && (
            <span
              className="text-xs italic text-primary"
              style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
            >
              {reason}
            </span>
          )}
        </div>
        {seeAllLabel && (
          <a href={seeAllNavigate || "#"} className="text-sm text-primary hover:brightness-110">
            {seeAllLabel} →
          </a>
        )}
      </header>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {cards.map((it, i) => (
          <a
            key={i}
            href={it.navigate || "#"}
            className="group grid grid-cols-[6rem_1fr] gap-3 rounded-xl bg-card border border-border p-2 hover:border-primary/40 transition"
          >
            <div className="aspect-square bg-muted rounded-lg overflow-hidden relative">
              {it.imageSrc ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={it.imageSrc} alt={it.title} className="absolute inset-0 w-full h-full object-cover" />
              ) : (
                <div
                  className="absolute inset-0"
                  style={{ background: "color-mix(in oklch, var(--color-primary) 10%, transparent)" }}
                />
              )}
            </div>
            <div className="flex flex-col gap-1 py-1 pr-1 min-w-0">
              {it.matchReason && (
                <span className="text-[10px] uppercase tracking-widest text-primary font-semibold truncate">
                  {it.matchReason}
                </span>
              )}
              <span className="text-sm font-medium text-foreground truncate">
                {it.title || <span className={skeleton("w-24")} />}
              </span>
              {it.subtitle && <span className="text-xs text-muted-foreground truncate">{it.subtitle}</span>}
              {it.price && <span className="text-sm text-foreground tabular-nums mt-auto">{it.price}</span>}
            </div>
          </a>
        ))}
      </div>
    </section>
  );
}
