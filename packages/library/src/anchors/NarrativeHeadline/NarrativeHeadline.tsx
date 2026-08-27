"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * NarrativeHeadline — analyst hero. Big number (or KPI trio) with a
 * one-sentence THESIS — what does the number mean? Analyst pages open
 * with a story, not a chart. Chart comes below.
 */
export const NarrativeHeadlineProps = z.object({
  eyebrow: z.string().optional(),          // "Q3 2025"
  headline: z.string().optional(),         // main number, e.g. "$4.2M"
  unit: z.string().optional(),             // "MRR"
  thesis: z.string().optional(),           // one-sentence narrative
  delta: z.string().optional(),            // "+12% vs Q2"
  deltaDirection: z.enum(["up", "down", "flat"]).optional(),
  ctaLabel: z.string().optional(),
  ctaNavigate: z.string().optional(),
});
export type NarrativeHeadlinePropsType = z.infer<typeof NarrativeHeadlineProps>;

const DELTA_TONE: Record<string, string> = {
  up: "text-green-600 bg-green-500/10 border-green-500/40",
  down: "text-red-600 bg-red-500/10 border-red-500/40",
  flat: "text-muted-foreground bg-muted border-border",
};

export function NarrativeHeadline(props: NarrativeHeadlinePropsType) {
  const { eyebrow, headline, unit, thesis, delta, deltaDirection, ctaLabel, ctaNavigate } = props;
  const tone = DELTA_TONE[deltaDirection || "flat"];
  return (
    <section
      data-anchor="narrative_headline"
      className="rounded-2xl border border-border bg-card p-8 md:p-10 flex flex-col gap-5"
    >
      {eyebrow && (
        <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">
          {eyebrow}
        </span>
      )}
      <div className="flex items-baseline flex-wrap gap-3">
        <span
          className="text-5xl md:text-6xl font-semibold tracking-tight tabular-nums text-foreground leading-none"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          {headline || <span className={skeleton("w-40")} />}
        </span>
        {unit && (
          <span className="text-xl text-muted-foreground font-medium">{unit}</span>
        )}
        {delta && (
          <span className={`ml-auto text-sm font-semibold border rounded-full px-3 py-1 tabular-nums ${tone}`}>
            {delta}
          </span>
        )}
      </div>
      {thesis && (
        <p
          className="text-lg md:text-xl text-foreground leading-relaxed max-w-prose"
          style={{ fontFamily: "var(--typography-font-heading, inherit)", textWrap: "balance" as any }}
        >
          {thesis}
        </p>
      )}
      {ctaLabel && (
        <a
          href={ctaNavigate || "#"}
          className="self-start text-sm font-medium text-primary underline underline-offset-4 decoration-primary/40 hover:decoration-primary"
        >
          {ctaLabel} →
        </a>
      )}
    </section>
  );
}
