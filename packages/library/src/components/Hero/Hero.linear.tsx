// packages/library/src/components/Hero/Hero.linear.tsx
import * as React from "react";
import type { HeroProps } from "./Hero";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Linear-register Hero variant.
 *
 * Visual language:
 *   - No background — minimal page header, just typography (elevation.flat)
 *   - Small-caps eyebrow in muted-foreground (density.compact)
 *   - Smaller headline (text-xl) — dense, developer-tools feel
 *   - Compact CTAs: small rounded-sm buttons in foreground/background
 *
 * Props mirror HeroProps exactly. CTA action wiring preserved.
 */

export type HeroLinearProps = HeroProps;

// Linear-register Hero is the page-level dominant heading. Sizing it
// smaller than section-level <Heading> nodes inverted the visual hierarchy
// — section titles like "All Tasks" (text-xl md:text-2xl) ended up larger
// than the page title "Tasks" (was text-xl), reading as upside-down flow.
// Bump page-title to text-2xl → text-3xl on desktop so the page header
// remains the largest element on the page. CTAs widened to h-9 to match
// the heavier headline.
// Use the platform's type-scale tokens (Tier S) so every page title across
// the system has identical rhythm. Editing the scale here ripples
// platform-wide via tailwind.config.ts.
const HERO = "px-6 py-6";
const EYEBROW = "text-micro uppercase text-muted-foreground mb-2";
const HEADLINE = "text-page-title text-foreground";
const SUBHEAD = "mt-2 text-body text-muted-foreground max-w-2xl";
const CTAS = "mt-2 flex items-center gap-2";

// CTA button reads brand primary from CSS vars injected by EngineProvider.
// bg-[var(--color-primary-500,...)] picks up the project's brand color; the
// theme() fallback preserves the original dark-foreground look when tokens
// are absent. text-[var(--color-surface-1,...)] ensures readable contrast.
// rounded-[var(--radius-sm,...)] lets projects override corner radius.
const CTA_BASE =
  "inline-flex items-center justify-center h-7 px-3 text-xs font-medium " +
  "rounded-[var(--radius-sm,0.125rem)] " +
  "bg-[var(--color-primary-500,theme(colors.slate.900))] " +
  "text-[var(--color-surface-1,theme(colors.white))] " +
  "hover:opacity-90 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

export function HeroLinear({
  eyebrow,
  headline,
  subhead,
  ctas,
  children,
  style,
  backgroundImage,
}: HeroLinearProps) {
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
              if (typeof c.action === "object" && c.action.type === "navigate") {
                return (
                  <a key={i} className={CTA_BASE} href={c.action.to}>
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
                  className={CTA_BASE}
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
