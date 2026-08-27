"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * ScanStrip — a horizontal strip of ~5-7 tappable cells for quick scanning.
 * Week days for a schedule, categories for a browse, price bars for a chart.
 * Semantic order matters: today/current is highlighted, others are muted.
 */
export const ScanStripProps = z.object({
  title: z.string().optional(),
  seeAllLabel: z.string().optional(),
  seeAllNavigate: z.string().optional(),
  cells: z.array(z.object({
    top: z.string(),           // e.g. day-of-week short
    main: z.string(),          // e.g. day number
    caption: z.string().optional(),
    active: z.boolean().optional(),
    navigate: z.string().optional(),
  })).min(1).max(12).optional(),
});
export type ScanStripPropsType = z.infer<typeof ScanStripProps>;

type _SS = NonNullable<ScanStripPropsType["cells"]>[number];
export function ScanStrip({ title, seeAllLabel, seeAllNavigate, cells }: ScanStripPropsType) {
  const items: _SS[] = cells && cells.length > 0
    ? cells
    : Array.from({ length: 7 }, () => ({ top: "", main: "" } as _SS));
  return (
    <section data-anchor="scan_strip" className="flex flex-col gap-3">
      {(title || seeAllLabel) && (
        <header className="flex items-baseline justify-between">
          {title != null && (
            <h3
              className="text-lg font-medium tracking-tight text-foreground"
              style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
            >
              {title || <span className={skeleton("w-32")} />}
            </h3>
          )}
          {seeAllLabel && (
            <a href={seeAllNavigate || "#"} className="text-sm text-primary hover:brightness-110">
              {seeAllLabel} →
            </a>
          )}
        </header>
      )}
      <div className={`grid gap-2`} style={{ gridTemplateColumns: `repeat(${Math.min(items.length, 7)}, minmax(0, 1fr))` }}>
        {items.slice(0, 7).map((c, i) => (
          <a
            key={i}
            href={c.navigate || "#"}
            data-active={c.active ? "true" : undefined}
            className={`flex flex-col items-center gap-1 px-2 py-3 rounded-xl border transition ${
              c.active
                ? "bg-primary text-primary-foreground border-primary shadow-sm"
                : "bg-card border-border text-foreground hover:bg-accent"
            }`}
          >
            <span className={`text-[10px] font-semibold uppercase tracking-widest ${c.active ? "opacity-85" : "text-muted-foreground"}`}>
              {c.top || <span className={skeleton("w-8")} />}
            </span>
            <span
              className="text-base tabular-nums font-medium tracking-tight leading-none mt-0.5"
              style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
            >
              {c.main || <span className={skeleton("w-6")} />}
            </span>
            {c.caption && (
              <span className={`text-[10px] ${c.active ? "opacity-85" : "text-muted-foreground"} leading-tight text-center`}>
                {c.caption}
              </span>
            )}
          </a>
        ))}
      </div>
    </section>
  );
}
