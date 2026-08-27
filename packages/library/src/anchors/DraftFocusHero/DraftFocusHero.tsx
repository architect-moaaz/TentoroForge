"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * DraftFocusHero — creator workspace hero. Centered on the CURRENT
 * work-in-progress: title, updated-at, wordcount/progress, resume CTA.
 * Not a task list — a "here's your draft, keep going" moment.
 */
export const DraftFocusHeroProps = z.object({
  eyebrow: z.string().optional(),          // "Draft"
  title: z.string().optional(),            // draft title
  snippet: z.string().optional(),          // first line of the draft
  updated: z.string().optional(),          // "Updated 2h ago"
  progress: z.string().optional(),         // "1,240 words · draft 3"
  ctaLabel: z.string().optional(),         // "Resume"
  ctaNavigate: z.string().optional(),
  secondaryLabel: z.string().optional(),
  secondaryNavigate: z.string().optional(),
});
export type DraftFocusHeroPropsType = z.infer<typeof DraftFocusHeroProps>;

export function DraftFocusHero(props: DraftFocusHeroPropsType) {
  const { eyebrow, title, snippet, updated, progress, ctaLabel, ctaNavigate, secondaryLabel, secondaryNavigate } = props;
  return (
    <section
      data-anchor="draft_focus_hero"
      className="rounded-2xl border border-border bg-card p-8 md:p-10 flex flex-col gap-4"
      style={{
        background:
          "linear-gradient(135deg, color-mix(in oklch, var(--color-primary) 8%, var(--color-card)), var(--color-card) 60%)",
      }}
    >
      <div className="flex items-center justify-between gap-4">
        {eyebrow && (
          <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">
            {eyebrow}
          </span>
        )}
        {updated && (
          <span className="text-xs text-muted-foreground tabular-nums">{updated}</span>
        )}
      </div>
      <h1
        className="text-2xl md:text-4xl font-medium tracking-tight text-foreground leading-tight"
        style={{ fontFamily: "var(--typography-font-heading, inherit)", textWrap: "balance" as any }}
      >
        {title || <span className={skeleton("w-64")} />}
      </h1>
      {snippet && (
        <p
          className="text-base md:text-lg text-muted-foreground leading-relaxed border-l-2 border-primary pl-4 italic max-w-prose"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          {snippet}
        </p>
      )}
      {progress && (
        <span className="text-xs font-medium text-muted-foreground tabular-nums">{progress}</span>
      )}
      <div className="flex flex-wrap items-center gap-3 mt-2">
        {ctaLabel && (
          <a
            href={ctaNavigate || "#"}
            className="inline-flex items-center h-11 px-6 rounded-full bg-primary text-primary-foreground text-sm font-semibold hover:brightness-110 transition"
          >
            {ctaLabel}
          </a>
        )}
        {secondaryLabel && (
          <a
            href={secondaryNavigate || "#"}
            className="text-sm font-medium text-foreground underline underline-offset-4 decoration-primary/40 hover:decoration-primary"
          >
            {secondaryLabel}
          </a>
        )}
      </div>
    </section>
  );
}
