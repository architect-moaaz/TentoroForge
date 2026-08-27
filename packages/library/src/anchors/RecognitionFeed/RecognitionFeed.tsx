"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * RecognitionFeed — the ambient "good things happened" strip on a manager's
 * dashboard. Wins, milestones, kudos. Warmer treatment than the rest of the
 * page — this is the counterbalance to the escalation queue.
 */
export const RecognitionFeedProps = z.object({
  title: z.string().optional(),
  seeAllLabel: z.string().optional(),
  seeAllNavigate: z.string().optional(),
  items: z.array(z.object({
    who: z.string(),
    what: z.string(),
    when: z.string().optional(),
    from: z.string().optional(),      // giver of kudos
    kind: z.enum(["win", "milestone", "kudos"]).optional(),
  })).min(1).max(6).optional(),
});
export type RecognitionFeedPropsType = z.infer<typeof RecognitionFeedProps>;

const KIND: Record<string, string> = { win: "🏆", milestone: "🎯", kudos: "💛" };

type _RF = NonNullable<RecognitionFeedPropsType["items"]>[number];
export function RecognitionFeed({ title, seeAllLabel, seeAllNavigate, items }: RecognitionFeedPropsType) {
  const rows: _RF[] = items && items.length > 0 ? items : Array.from({ length: 3 }, () => ({ who: "", what: "" } as _RF));
  return (
    <section
      data-anchor="recognition_feed"
      className="rounded-2xl border border-border overflow-hidden"
      style={{ background: "linear-gradient(180deg, color-mix(in oklch, var(--color-primary) 6%, var(--color-card)), var(--color-card))" }}
    >
      <header className="flex items-baseline justify-between px-5 py-3 border-b border-border">
        <h3
          className="text-sm font-semibold tracking-tight text-foreground flex items-center gap-2"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          <span aria-hidden="true">✨</span>
          {title || "Wins & recognition"}
        </h3>
        {seeAllLabel && (
          <a href={seeAllNavigate || "#"} className="text-xs text-primary hover:brightness-110">
            {seeAllLabel} →
          </a>
        )}
      </header>
      <ul className="flex flex-col">
        {rows.map((r, i) => (
          <li key={i} className="grid grid-cols-[auto_1fr_auto] gap-3 items-start px-5 py-3 border-b border-border last:border-b-0">
            <span className="text-lg leading-none pt-1" aria-hidden="true">{KIND[r.kind || "win"]}</span>
            <div className="flex flex-col gap-0.5 min-w-0">
              <p className="text-sm leading-snug text-foreground">
                <span className="font-medium">{r.who || <span className={skeleton("w-20")} />}</span>{" "}
                <span className="text-muted-foreground">{r.what || <span className={skeleton("w-32")} />}</span>
              </p>
              {r.from && (
                <span
                  className="text-xs italic text-primary"
                  style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
                >
                  — {r.from}
                </span>
              )}
            </div>
            {r.when && <span className="text-[11px] text-muted-foreground tabular-nums pt-1">{r.when}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
