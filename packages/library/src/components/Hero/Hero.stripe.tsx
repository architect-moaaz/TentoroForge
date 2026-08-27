// packages/library/src/components/Hero/Hero.stripe.tsx
import * as React from "react";
import type { HeroProps } from "./Hero";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Stripe-register Hero variant.
 *
 * Visual language:
 *   - Gradient background from-primary/10 via-card to-card with soft border
 *   - Big confident headline (text-4xl, font-bold) — fintech confidence
 *   - Small caps eyebrow in primary color
 *   - Prominent CTA buttons with shadow-sm for subtle depth
 *   - Rounded-md + generous padding (radius.soft, density.comfortable)
 *
 * Props mirror HeroProps exactly. CTA action wiring preserved.
 */

export type HeroStripeProps = HeroProps;

const HERO = "rounded-md bg-gradient-to-br from-primary/10 via-card to-card border border-border px-4 py-6 sm:px-8 sm:py-10";
const EYEBROW = "text-xs font-semibold uppercase tracking-wide text-primary mb-2";
const HEADLINE = "text-2xl sm:text-4xl font-bold leading-tight tracking-tight text-foreground";
const SUBHEAD = "mt-3 text-base text-muted-foreground max-w-2xl";
const CTAS = "mt-6 flex flex-wrap items-center gap-3";

const CTA_PRIMARY =
  "inline-flex items-center justify-center h-10 px-5 text-sm font-semibold rounded-md " +
  "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

const CTA_SECONDARY =
  "inline-flex items-center justify-center h-10 px-5 text-sm font-semibold rounded-md " +
  "border border-border bg-card text-foreground shadow-sm hover:bg-muted " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

export function HeroStripe({
  eyebrow,
  headline,
  subhead,
  ctas,
  children,
  style,
  backgroundImage,
}: HeroStripeProps) {
  const motionProps = useMotion(style?.motion);
  const bgImageStyle: React.CSSProperties = backgroundImage
    ? {
        backgroundImage: `url(${backgroundImage.url})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
        position: "relative",
      }
    : {};
  return (
    <header className={HERO} style={{ ...bgImageStyle, ...resolveStyle(style) }} {...motionProps}>
      {backgroundImage && (
        <div
          data-hero-scrim
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            backgroundColor: "#000",
            opacity: backgroundImage.overlay ?? 0.4,
            pointerEvents: "none",
          }}
        />
      )}
      <div data-hero-content style={backgroundImage ? { position: "relative", zIndex: 1 } : undefined}>
        {eyebrow && <p className={EYEBROW}>{eyebrow}</p>}
        {headline && <h1 className={HEADLINE}>{headline}</h1>}
        {subhead && <p className={SUBHEAD}>{subhead}</p>}
        {ctas && ctas.length > 0 && (
          <div className={CTAS}>
            {ctas.map((c, i) => {
              const cls = i === 0 ? CTA_PRIMARY : CTA_SECONDARY;
              if (typeof c.action === "object" && c.action.type === "navigate") {
                return (
                  <a key={i} className={cls} href={c.action.to}>
                    {c.label}
                  </a>
                );
              }
              const dataAttr =
                typeof c.action === "object" && c.action.type === "workflow"
                  ? `workflow:${c.action.name}`
                  : undefined;
              return (
                <button
                  key={i}
                  type="button"
                  className={cls}
                  data-cta-action={dataAttr}
                >
                  {c.label}
                </button>
              );
            })}
          </div>
        )}
        {children}
      </div>
    </header>
  );
}
