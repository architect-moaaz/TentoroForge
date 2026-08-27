"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * TrendingRail — what other people are buying / watching / booking right now.
 * Product-card scroll rail with a social-proof line per card ("142 sold this week").
 * Product-first: image tile dominates the card.
 */
export const TrendingRailProps = z.object({
  title: z.string().optional(),
  seeAllLabel: z.string().optional(),
  seeAllNavigate: z.string().optional(),
  items: z.array(z.object({
    imageSrc: z.string().optional(),
    title: z.string(),
    price: z.string().optional(),
    socialProof: z.string().optional(),  // "142 sold this week"
    navigate: z.string().optional(),
  })).min(1).max(8).optional(),
});
export type TrendingRailPropsType = z.infer<typeof TrendingRailProps>;

type _TR = NonNullable<TrendingRailPropsType["items"]>[number];
export function TrendingRail({ title, seeAllLabel, seeAllNavigate, items }: TrendingRailPropsType) {
  const cards: _TR[] = items && items.length > 0 ? items : Array.from({ length: 4 }, () => ({ title: "" } as _TR));
  return (
    <section data-anchor="trending_rail" className="flex flex-col gap-3">
      <header className="flex items-baseline justify-between">
        <h3
          className="text-lg font-medium tracking-tight text-foreground"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          {title || "Trending now"}
        </h3>
        {seeAllLabel && (
          <a href={seeAllNavigate || "#"} className="text-sm text-primary hover:brightness-110">
            {seeAllLabel} →
          </a>
        )}
      </header>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {cards.map((it, i) => (
          <a
            key={i}
            href={it.navigate || "#"}
            className="group flex flex-col gap-2 rounded-xl bg-card border border-border overflow-hidden hover:border-primary/40 transition"
          >
            <div className="aspect-square bg-muted relative">
              {it.imageSrc ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={it.imageSrc} alt={it.title} className="absolute inset-0 w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" />
              ) : (
                <div
                  className="absolute inset-0"
                  style={{ background: "color-mix(in oklch, var(--color-primary) 8%, transparent)" }}
                />
              )}
            </div>
            <div className="flex flex-col gap-0.5 px-3 pb-3">
              <span className="text-sm font-medium text-foreground truncate">
                {it.title || <span className={skeleton("w-24")} />}
              </span>
              <div className="flex items-baseline justify-between gap-2">
                {it.price && <span className="text-sm text-foreground tabular-nums">{it.price}</span>}
                {it.socialProof && (
                  <span className="text-[10px] text-muted-foreground truncate">{it.socialProof}</span>
                )}
              </div>
            </div>
          </a>
        ))}
      </div>
    </section>
  );
}
