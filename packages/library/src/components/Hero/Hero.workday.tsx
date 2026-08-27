// packages/library/src/components/Hero/Hero.workday.tsx
import * as React from "react";
import type { HeroProps } from "./Hero";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Workday-register Hero variant.
 *
 * Visual language:
 *   - Border-bottom page-header treatment (not full-bleed banner)
 *   - Surface-1 background (subtle gray, bg-muted/30)
 *   - Eyebrow in primary navy color
 *   - Compact CTAs: bordered style with primary-on-hover
 *
 * Props mirror HeroProps exactly. CTA action wiring preserved:
 *   - action.type === "navigate" → <a href={action.to}>
 *   - action.type === "workflow"  → <button data-cta-action="workflow:{name}">
 */

export type HeroWorkdayProps = HeroProps;

const HERO =
  "w-full border-b border-border bg-muted/30 px-4 pt-6 pb-4 sm:px-8 sm:pt-8 sm:pb-6";
const EYEBROW =
  "text-[11px] font-semibold uppercase tracking-[0.1em] text-primary mb-2";
const HEADLINE =
  "text-2xl sm:text-3xl font-bold leading-tight tracking-tight text-foreground";
const SUBHEAD =
  "mt-2 text-sm text-muted-foreground max-w-2xl";
const CTAS = "mt-5 flex flex-wrap items-center gap-3";

const CTA_BASE =
  "inline-flex items-center justify-center gap-2 h-9 px-4 text-sm font-medium " +
  "border border-border bg-card transition-colors " +
  "hover:bg-primary hover:text-primary-foreground hover:border-primary " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

export function HeroWorkday({
  eyebrow,
  headline,
  subhead,
  ctas,
  children,
  style,
  backgroundImage,
}: HeroWorkdayProps) {
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
    <header
      className={HERO}
      style={{ ...bgImageStyle, ...resolveStyle(style) }}
      {...motionProps}
    >
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
        <h1 className={HEADLINE}>{headline}</h1>
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
