import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { HeroPropsType } from "./Hero.schema";
import { resolveStyle, resolveStyleNoBackground } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useTokens } from "../../theme/tokens-context";
import { SurfaceBackground } from "../surfaces/SurfaceBackground";
import { IllustrationResolver } from "../surfaces/IllustrationResolver";

/**
 * Hero — page-leading headline block. Three layouts:
 *   centered: text centered, media below (or none)
 *   split:    text left, media right at md+ (stacked on mobile)
 *   stacked:  text top, media bottom
 *
 * role prop drives padding/border treatment:
 *   banner   — default; today's appearance (no visual change)
 *   headline — full-bleed page header with border-b
 *   inline   — compact single-line treatment
 *
 * Wave 2: when role is undefined (defaults to banner), typography.scaleMode
 * drives headline/subhead sizes. balanced = today's appearance (zero drift).
 *
 * Renders with shadcn/Tailwind utilities so the project's globals.css
 * styles match the rest of the generated app.
 */
export interface HeroProps extends Omit<HeroPropsType, "backgroundImage"> {
  style?: StyleSlotT;
  children?: React.ReactNode;
  backgroundImage?: { url: string; overlay?: number };
}

// Role-based outer container class sets.
// banner = today's default appearance (preserved exactly for zero drift).
const ROLE_CLASSES = {
  banner:   "w-full px-4 sm:px-6 lg:px-8 py-12 md:py-16",
  headline: "w-full px-8 py-12 border-b border-border",
  inline:   "w-full px-4 py-2",
} as const;

// Role-based headline/subhead font sizes.
const ROLE_HEADLINE_CLASS = {
  banner:   "text-3xl md:text-4xl lg:text-5xl font-semibold tracking-tight text-foreground leading-tight",
  headline: "text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight text-foreground leading-tight",
  inline:   "text-lg md:text-xl font-semibold tracking-tight text-foreground leading-tight",
} as const;

const ROLE_SUBHEAD_CLASS = {
  banner:   "text-base md:text-lg text-muted-foreground leading-relaxed max-w-2xl",
  headline: "text-lg md:text-xl text-muted-foreground leading-relaxed max-w-3xl",
  inline:   "text-sm text-muted-foreground leading-relaxed",
} as const;

// Wave 2: scaleMode-aware headline/subhead classes for the no-role (banner) path.
// balanced = today's banner appearance (preserved exactly for zero drift).
const SCALE_HEADLINE_CLASS: Record<"tight" | "balanced" | "dramatic", string> = {
  tight:    "text-xl font-semibold tracking-tight text-foreground leading-tight",
  balanced: ROLE_HEADLINE_CLASS.banner,   // ← exact today's appearance
  dramatic: "text-4xl font-semibold tracking-tight text-foreground leading-tight",
};

const SCALE_SUBHEAD_CLASS: Record<"tight" | "balanced" | "dramatic", string> = {
  tight:    "text-sm text-muted-foreground leading-relaxed max-w-2xl",
  balanced: ROLE_SUBHEAD_CLASS.banner,    // ← exact today's appearance
  dramatic: "text-lg text-muted-foreground leading-relaxed max-w-2xl",
};

const CTA_BASE =
  "inline-flex items-center justify-center gap-2 h-10 px-4 rounded-md text-sm " +
  "font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-ring focus-visible:ring-offset-2";
const CTA_VARIANT: Record<string, string> = {
  primary:   "bg-primary text-primary-foreground hover:bg-primary/90",
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border",
  ghost:     "bg-transparent text-foreground hover:bg-accent hover:text-accent-foreground",
};

export function Hero(props: HeroProps) {
  // ctas is optional in Hero.schema — default it, or `ctas.length` crashes
  // the node (caught by NodeErrorBoundary, but the hero renders as an error).
  const { eyebrow, headline, subhead, layout, role, ctas = [],
          media, illustration, style, children, backgroundImage } = props;
  // __illustrationBasePath is a private prop injected at the registry layer
  // (SchemaRendererWrapper) so the scaffold can resolve illustration slugs
  // under /p/<projectId>/illustrations. Standalone apps omit it and the
  // IllustrationResolver default (/illustrations) wins.
  const illustrationBasePath = (props as { __illustrationBasePath?: string })
    .__illustrationBasePath;

  const tokens = useTokens();
  const scaleMode = tokens.typography.scaleMode as "tight" | "balanced" | "dramatic";
  const resolvedRole = role ?? "banner";
  const sectionClass = ROLE_CLASSES[resolvedRole];

  // When role is explicitly set, role wins (Wave 1 behavior preserved).
  // When role is absent (defaults to "banner"), scaleMode drives text sizing:
  //   balanced = today's appearance; tight/dramatic = new variants.
  const headlineClass = role
    ? ROLE_HEADLINE_CLASS[resolvedRole]
    : SCALE_HEADLINE_CLASS[scaleMode];
  const subheadClass = role
    ? ROLE_SUBHEAD_CLASS[resolvedRole]
    : SCALE_SUBHEAD_CLASS[scaleMode];

  const hasIllustration = !!illustration?.slug;
  // Illustration forces a 2-column layout even when layout="centered" so the
  // bundled SVG renders beside the content. layout="split" already produces a
  // 2-column grid via containerClass, so we don't double-wrap there.
  const isSplit = layout === "split";
  const isStacked = layout === "stacked";
  const useIllustrationGrid = hasIllustration && !isSplit;
  const containerClass = isSplit
    ? "grid gap-8 md:grid-cols-2 md:items-center max-w-7xl mx-auto"
    : useIllustrationGrid
      ? "grid gap-8 md:grid-cols-2 md:items-center max-w-7xl mx-auto"
      : "max-w-3xl mx-auto" + (isStacked ? " flex flex-col gap-8" : " text-center");

  const textColumn = (
    <div className="flex flex-col gap-4">
      {eyebrow && (
        <p className="text-xs font-semibold uppercase tracking-wider text-primary">
          {eyebrow}
        </p>
      )}
      <h1 className={headlineClass}>
        {headline}
      </h1>
      {subhead && (
        <p className={subheadClass}>
          {subhead}
        </p>
      )}
      {ctas.length > 0 && (
        <div className={`flex flex-wrap gap-3 mt-2 ${isSplit || isStacked || useIllustrationGrid ? "" : "justify-center"}`}>
          {ctas.map((c, i) => {
            const variant = c.variant ?? "primary";
            const cls = `${CTA_BASE} ${CTA_VARIANT[variant] ?? CTA_VARIANT.primary}`;
            if (typeof c.action === "object" && c.action.type === "navigate") {
              return <a key={i} className={cls} href={c.action.to}>{c.label}</a>;
            }
            const dataAttr = (typeof c.action === "object" && c.action.type === "workflow")
              ? `workflow:${c.action.name}` : undefined;
            return (
              <button key={i} type="button" className={cls} data-cta-action={dataAttr}>
                {c.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );

  const illustrationColumn = hasIllustration && illustration ? (
    <IllustrationResolver
      slug={illustration.slug}
      alt={illustration.alt ?? ""}
      basePath={illustrationBasePath ?? "/illustrations"}
      className="max-w-md w-full h-auto"
    />
  ) : null;

  // backgroundImage: cover-size photo background with optional scrim overlay.
  const bgImageStyle: React.CSSProperties = backgroundImage
    ? {
        backgroundImage: `url(${backgroundImage.url})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
        position: "relative",
      }
    : {};

  const scrim = backgroundImage ? (
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
  ) : null;

  const innerContent = (
    <>
      {scrim}
      <div
        data-hero-content
        className={containerClass}
        style={backgroundImage ? { position: "relative", zIndex: 1 } : undefined}
      >
        {textColumn}
        {illustrationColumn}
        {media && (
          <div className="rounded-xl overflow-hidden bg-muted/40">
            {media.kind === "image"
              ? <img className="w-full h-auto object-cover" src={media.src} alt={media.alt ?? ""} />
              : <object className="w-full h-auto" data={media.src} type="image/svg+xml" aria-label={media.alt ?? ""} />}
          </div>
        )}
        {children}
      </div>
    </>
  );

  // When style.background is set, render the outer surface via SurfaceBackground
  // so the gradient/solid backdrop is emitted by the shared backdrop component.
  // Padding/radius/shadow/motion still flow through inline style. When background
  // is absent, keep the existing <section> for semantics and DOM stability.
  if (style?.background) {
    return (
      <SurfaceBackground
        background={style.background}
        className={sectionClass}
        data-hero-layout={layout}
        data-hero-role={resolvedRole}
        style={{ ...bgImageStyle, ...resolveStyleNoBackground(style) }}
        {...useMotion(style?.motion)}
      >
        {innerContent}
      </SurfaceBackground>
    );
  }

  return (
    <section
      className={sectionClass}
      data-hero-layout={layout}
      data-hero-role={resolvedRole}
      style={{ ...bgImageStyle, ...resolveStyle(style) }}
      {...useMotion(style?.motion)}
    >
      {innerContent}
    </section>
  );
}
