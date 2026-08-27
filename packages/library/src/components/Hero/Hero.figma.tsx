// packages/library/src/components/Hero/Hero.figma.tsx
import * as React from "react";
import type { HeroProps } from "./Hero";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Figma-register Hero variant.
 *
 * Visual language:
 *   - Colorful gradient background (from-primary/15 via-secondary/10 to-accent/10)
 *   - Rounded-2xl container with shadow-lg (elevation.floating)
 *   - Vibrant eyebrow in primary color, bold all-caps
 *   - Big extrabold headline (text-5xl, font-extrabold) — weight 800
 *   - Larger subhead for expressive scale
 *   - CTAs: rounded-full buttons, bold, primary bg + white text (playful)
 *
 * Props mirror HeroProps exactly. CTA action wiring preserved.
 */

export type HeroFigmaProps = HeroProps;

const HERO = "rounded-2xl bg-gradient-to-br from-primary/15 via-secondary/10 to-accent/10 border border-border px-4 py-8 sm:px-8 sm:py-12 shadow-lg";
const EYEBROW = "text-sm font-bold uppercase tracking-wider text-primary mb-3";
const HEADLINE = "text-3xl sm:text-5xl font-extrabold leading-tight tracking-tight text-foreground";
const SUBHEAD = "mt-4 text-base sm:text-lg text-muted-foreground max-w-2xl";
const CTAS = "mt-6 flex items-center gap-3";

const CTA_PRIMARY =
  "inline-flex items-center justify-center h-11 px-6 text-sm font-bold rounded-full " +
  "bg-primary text-primary-foreground shadow-md hover:bg-primary/90 hover:shadow-lg " +
  "transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

const CTA_SECONDARY =
  "inline-flex items-center justify-center h-11 px-6 text-sm font-bold rounded-full " +
  "border border-border bg-card text-foreground shadow-sm hover:bg-muted hover:shadow-md " +
  "transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

export function HeroFigma({
  eyebrow,
  headline,
  subhead,
  ctas,
  children,
  style,
  backgroundImage,
}: HeroFigmaProps) {
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
