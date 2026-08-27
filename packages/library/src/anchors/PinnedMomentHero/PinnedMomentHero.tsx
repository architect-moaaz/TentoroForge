"use client";
import * as React from "react";
import { z } from "zod";
import { useSurfaceClasses, skeleton } from "../anchor-shared";

/**
 * PinnedMomentHero — "the thing you came here for right now."
 *
 * Top of a member_home. Names the next class, the next bill, the next event
 * — whatever the recipe's brief said this member cares about most. Never
 * a Table+Stat CRUD skeleton; always a moment.
 *
 * Copy slots: eyebrow (small tag above), headline (the moment itself),
 * subhead (context — when/where/who).
 *
 * Binds: dataSource (the entity this moment describes).
 */
export const PinnedMomentHeroProps = z.object({
  eyebrow: z.string().optional(),
  headline: z.string().optional(),
  subhead: z.string().optional(),
  note: z.string().optional(),
  ctaLabel: z.string().optional(),
  ctaNavigate: z.string().optional(),
  secondaryLabel: z.string().optional(),
  secondaryNavigate: z.string().optional(),
});
export type PinnedMomentHeroPropsType = z.infer<typeof PinnedMomentHeroProps>;

export function PinnedMomentHero({
  eyebrow, headline, subhead, note, ctaLabel, ctaNavigate, secondaryLabel, secondaryNavigate,
}: PinnedMomentHeroPropsType) {
  const surface = useSurfaceClasses();
  return (
    <section
      data-anchor="pinned_moment_hero"
      className={`${surface} flex flex-col gap-3`}
      style={{ background: "linear-gradient(135deg, var(--color-surface-hero, var(--color-surface-2)), var(--color-surface-1))" }}
    >
      {eyebrow != null && (
        <span className="text-xs font-semibold uppercase tracking-widest text-primary flex items-center gap-2 before:content-[''] before:h-px before:w-6 before:bg-primary">
          {eyebrow || <span className={skeleton("w-24")} />}
        </span>
      )}
      <h2
        className="font-semibold tracking-tight text-foreground leading-[1.05]"
        style={{ fontFamily: "var(--typography-font-heading, inherit)", fontSize: "clamp(1.75rem, 3.5vw, 2.5rem)" }}
      >
        {headline || <span className={skeleton("w-64")} />}
      </h2>
      {subhead != null && (
        <p className="text-sm text-muted-foreground">{subhead || <span className={skeleton("w-48")} />}</p>
      )}
      {note && (
        <p
          className="text-sm italic text-muted-foreground border-l-2 border-primary pl-3 mt-1 leading-relaxed"
          style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
        >
          {note}
        </p>
      )}
      {(ctaLabel || secondaryLabel) && (
        <div className="flex flex-wrap items-center gap-2 mt-2">
          {ctaLabel && (
            <a
              href={ctaNavigate || "#"}
              className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-primary text-primary-foreground text-sm font-medium hover:brightness-110 transition"
            >
              {ctaLabel}
            </a>
          )}
          {secondaryLabel && (
            <a
              href={secondaryNavigate || "#"}
              className="inline-flex items-center gap-2 h-10 px-5 rounded-full bg-transparent border border-border text-foreground text-sm hover:bg-accent transition"
            >
              {secondaryLabel}
            </a>
          )}
        </div>
      )}
    </section>
  );
}
