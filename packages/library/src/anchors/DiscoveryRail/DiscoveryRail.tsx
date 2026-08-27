"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * DiscoveryRail — horizontal browse-more rail with category chips.
 * Used by learner_home and patron_events (and any "here are other
 * things you might like" surface). Not curated — categorical.
 */
export const DiscoveryRailProps = z.object({
  title: z.string().optional(),
  seeAllLabel: z.string().optional(),
  seeAllNavigate: z.string().optional(),
  categories: z.array(z.object({
    label: z.string(),
    count: z.number().int().nonnegative().optional(),
    icon: z.string().optional(),
    navigate: z.string().optional(),
  })).min(1).max(8).optional(),
});
export type DiscoveryRailPropsType = z.infer<typeof DiscoveryRailProps>;

type _DR = NonNullable<DiscoveryRailPropsType["categories"]>[number];
export function DiscoveryRail({ title, seeAllLabel, seeAllNavigate, categories }: DiscoveryRailPropsType) {
  const cats: _DR[] = categories && categories.length > 0
    ? categories
    : Array.from({ length: 5 }, () => ({ label: "" } as _DR));
  return (
    <section data-anchor="discovery_rail" className="flex flex-col gap-3">
      <header className="flex items-baseline justify-between">
        <h3
          className="text-lg font-medium tracking-tight text-foreground"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          {title || "Explore"}
        </h3>
        {seeAllLabel && (
          <a href={seeAllNavigate || "#"} className="text-sm text-primary hover:brightness-110">
            {seeAllLabel} →
          </a>
        )}
      </header>
      <div className="flex flex-wrap gap-2">
        {cats.map((c, i) => (
          <a
            key={i}
            href={c.navigate || "#"}
            className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-2 text-sm text-foreground hover:border-primary/50 hover:bg-accent transition"
          >
            {c.icon && <span aria-hidden="true">{c.icon}</span>}
            <span className="font-medium">
              {c.label || <span className={skeleton("w-16")} />}
            </span>
            {typeof c.count === "number" && (
              <span className="text-xs text-muted-foreground tabular-nums">{c.count}</span>
            )}
          </a>
        ))}
      </div>
    </section>
  );
}
