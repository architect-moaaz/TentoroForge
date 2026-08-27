// packages/library/src/components/Hero/Hero.notion.tsx
import * as React from "react";
import type { HeroProps } from "./Hero";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Notion-register Hero variant.
 *
 * Visual language:
 *   - Generous space (density.spacious), no background color (content-first)
 *   - Serif headline — content reads first, not chrome
 *   - Simple eyebrow in muted gray, no all-caps
 *   - CTAs: subtle text links with underline-on-hover — not buttons
 *   - Rounded-lg wrapper (radius.round)
 *   - Flat elevation — no shadow, no gradient
 *
 * Props mirror HeroProps exactly. CTA action wiring preserved.
 */

export type HeroNotionProps = HeroProps;

const HERO = "px-4 py-8 sm:px-8 sm:py-12";
const EYEBROW = "text-sm text-muted-foreground mb-3";
const HEADLINE = "text-2xl sm:text-4xl font-bold leading-tight tracking-tight text-foreground";
const SUBHEAD = "mt-3 text-base text-muted-foreground max-w-2xl";
const CTAS = "mt-6 flex items-center gap-4";

const CTA_LINK =
  "text-sm text-foreground underline-offset-4 hover:underline focus-visible:outline-none " +
  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

export function HeroNotion({
  eyebrow,
  headline,
  subhead,
  ctas,
  children,
  style,
  backgroundImage,
}: HeroNotionProps) {
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
                  <a key={i} className={CTA_LINK} href={c.action.to}>
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
                  className={CTA_LINK}
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
