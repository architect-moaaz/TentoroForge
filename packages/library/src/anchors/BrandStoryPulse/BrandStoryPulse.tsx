"use client";
import * as React from "react";
import { z } from "zod";
import { skeleton } from "../anchor-shared";

/**
 * BrandStoryPulse — the "story of the brand" slot on a shopper home.
 * Not a promo. A short editorial: title, one paragraph, one link. Uses
 * the display serif more heavily than the rest of the page.
 */
export const BrandStoryPulseProps = z.object({
  eyebrow: z.string().optional(),
  title: z.string().optional(),
  body: z.string().optional(),
  ctaLabel: z.string().optional(),
  ctaNavigate: z.string().optional(),
  imageSrc: z.string().optional(),
});
export type BrandStoryPulsePropsType = z.infer<typeof BrandStoryPulseProps>;

export function BrandStoryPulse(props: BrandStoryPulsePropsType) {
  const { eyebrow, title, body, ctaLabel, ctaNavigate, imageSrc } = props;
  return (
    <section
      data-anchor="brand_story_pulse"
      className="grid grid-cols-1 md:grid-cols-[1fr_1.4fr] gap-6 rounded-2xl border border-border overflow-hidden bg-card"
    >
      <div className="aspect-[4/3] md:aspect-auto bg-muted relative min-h-[200px]">
        {imageSrc ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={imageSrc} alt={title || ""} className="absolute inset-0 w-full h-full object-cover" />
        ) : (
          <div
            className="absolute inset-0"
            style={{
              background: "radial-gradient(circle at 30% 20%, color-mix(in oklch, var(--color-primary) 25%, transparent), transparent 60%)",
            }}
          />
        )}
      </div>
      <div className="flex flex-col justify-center gap-4 p-8 md:p-10">
        {eyebrow && (
          <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">
            {eyebrow}
          </span>
        )}
        <h2
          className="text-2xl md:text-3xl font-medium tracking-tight text-foreground leading-tight"
          style={{ fontFamily: "var(--typography-font-heading, inherit)", textWrap: "balance" as any }}
        >
          {title || <span className={skeleton("w-48")} />}
        </h2>
        {body && (
          <p
            className="text-base text-muted-foreground leading-relaxed max-w-prose"
            style={{ fontFamily: "var(--typography-font-heading, inherit)" }}
          >
            {body}
          </p>
        )}
        {ctaLabel && (
          <a
            href={ctaNavigate || "#"}
            className="self-start mt-1 inline-flex items-center h-10 text-sm font-medium text-primary underline underline-offset-4 decoration-primary/40 hover:decoration-primary"
          >
            {ctaLabel} →
          </a>
        )}
      </div>
    </section>
  );
}
