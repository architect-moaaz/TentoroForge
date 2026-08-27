"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * FeaturedMomentHero — shopper's top-of-page moment. One curated product
 * or story, hero-scale, with the reason it's here (collection, edit, drop).
 * Landing page energy inside an app, on purpose.
 */
export const FeaturedMomentHeroProps = z.object({
  eyebrow: z.string().optional(),      // "This week's edit", "Fall drop"
  headline: z.string().optional(),
  subhead: z.string().optional(),
  imageSrc: z.string().optional(),
  imageAlt: z.string().optional(),
  ctaLabel: z.string().optional(),
  ctaNavigate: z.string().optional(),
  secondaryLabel: z.string().optional(),
  secondaryNavigate: z.string().optional(),
});
export type FeaturedMomentHeroPropsType = z.infer<typeof FeaturedMomentHeroProps>;

export function FeaturedMomentHero(props: FeaturedMomentHeroPropsType) {
  const { eyebrow, headline, subhead, imageSrc, imageAlt, ctaLabel, ctaNavigate, secondaryLabel, secondaryNavigate } = props;
  return (
    <section
      data-anchor="featured_moment_hero"
      className="relative grid grid-cols-1 lg:grid-cols-2 gap-6 rounded-2xl overflow-hidden border border-border bg-card"
    >
      <div className="flex flex-col justify-center gap-4 p-8 md:p-12 order-2 lg:order-1">
        {eyebrow && (
          <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">
            {eyebrow}
          </span>
        )}
        <h1
          className="text-3xl md:text-5xl font-medium tracking-tight text-foreground leading-tight"
          style={{ fontFamily: "var(--typography-font-heading, inherit)", textWrap: "balance" as any }}
        >
          {headline || <span className={skeleton("w-64")} />}
        </h1>
        {subhead && (
          <p className="text-base md:text-lg text-muted-foreground max-w-prose leading-relaxed">
            {subhead}
          </p>
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
              className="inline-flex items-center h-11 px-4 text-sm font-medium text-foreground underline underline-offset-4 decoration-primary/50 hover:decoration-primary"
            >
              {secondaryLabel} →
            </a>
          )}
        </div>
      </div>
      <div className="order-1 lg:order-2 min-h-[240px] bg-muted relative">
        {imageSrc ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={imageSrc} alt={imageAlt || headline || ""} className="absolute inset-0 w-full h-full object-cover" />
        ) : (
          <div
            className="absolute inset-0"
            style={{
              background: "linear-gradient(135deg, color-mix(in oklch, var(--color-primary) 20%, transparent), color-mix(in oklch, var(--color-primary) 5%, transparent))",
            }}
          />
        )}
      </div>
    </section>
  );
}
