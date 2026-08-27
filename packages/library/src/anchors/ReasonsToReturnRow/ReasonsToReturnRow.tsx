"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * ReasonsToReturnRow — three quick reasons this shopper should come back.
 * Not a stat strip — each reason is a claim ("Free returns", "New drops
 * every Friday", "Members-only prices") with an icon-y glyph and a
 * one-line proof.
 */
export const ReasonsToReturnRowProps = z.object({
  items: z.array(z.object({
    glyph: z.string().optional(),  // emoji or single letter
    title: z.string(),
    proof: z.string().optional(),
  })).min(1).max(4).optional(),
});
export type ReasonsToReturnRowPropsType = z.infer<typeof ReasonsToReturnRowProps>;

type _RRR2 = NonNullable<ReasonsToReturnRowPropsType["items"]>[number];
export function ReasonsToReturnRow({ items }: ReasonsToReturnRowPropsType) {
  const rows: _RRR2[] = items && items.length > 0 ? items : Array.from({ length: 3 }, () => ({ title: "" } as _RRR2));
  const cols = rows.length === 1 ? "grid-cols-1" : rows.length === 2 ? "grid-cols-1 sm:grid-cols-2" : "grid-cols-1 sm:grid-cols-3";
  return (
    <section data-anchor="reasons_to_return_row" className={`grid ${cols} gap-3`}>
      {rows.map((r, i) => (
        <div key={i} className="flex items-start gap-3 rounded-xl border border-border bg-card p-5">
          <span
            className="shrink-0 h-10 w-10 rounded-full grid place-items-center text-lg"
            style={{
              background: "color-mix(in oklch, var(--color-primary) 15%, transparent)",
              color: "var(--color-primary)",
            }}
            aria-hidden="true"
          >
            {r.glyph || "★"}
          </span>
          <div className="flex-1 min-w-0">
            <h3
              className="text-sm font-semibold text-foreground leading-tight"
              style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
            >
              {r.title || <span className={skeleton("w-32")} />}
            </h3>
            {r.proof && (
              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{r.proof}</p>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}
