import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SectionPropsType } from "./Section.schema";
import { resolveStyle, resolveStyleNoBackground } from "../../style/resolveStyle";
import { dataAttrProps, withCallerClass } from "../../util/passthroughAttrs";
import { useMotion } from "../../style/useMotion";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useDensity, useElevation, useRadiusScale } from "../../theme/tokens-context";
import type { RadiusScale } from "../../theme/token-types";
import { SurfaceBackground } from "../surfaces/SurfaceBackground";
import { IllustrationResolver } from "../surfaces/IllustrationResolver";

/**
 * Section — content block with optional header. Variants control the visual
 * treatment of the wrapper. All variants render with shadcn/Tailwind utilities
 * so the project's globals.css styles match the rest of the generated app.
 *
 * role prop (optional) overrides the variant-based class:
 *   content  — default; maps to today's variant-driven appearance (no drift)
 *   headline — top-of-page treatment with bottom border
 *   aside    — muted sidebar treatment with rounded background
 *   footer   — bottom-of-page treatment with top border
 *
 * Wave 2: when role is undefined, density + elevation tokens drive padding/shadow.
 * Defaults (comfortable + layered) preserve today's appearance exactly.
 *
 * variant="full-bleed": escapes the parent container width by negative-margin
 * breakout (width:100vw, margin-left:50%, transform:translateX(-50%)) so the
 * section spans edge-to-edge of the viewport even inside a bounded max-width
 * container. The structural inline styles are applied before any user style
 * overrides so they can still be overridden via the style slot.
 */
const FULL_BLEED_STYLE: React.CSSProperties = {
  width: "100vw",
  marginLeft: "50%",
  transform: "translateX(-50%)",
};

function variantClass(variant: string, radiusScale: RadiusScale): string {
  const radius = RADIUS_SURFACE_CLASS[radiusScale];
  switch (variant) {
    case "feature":    return `bg-card text-card-foreground ${radius} border shadow-sm p-6 md:p-8`;
    case "cta":        return `bg-primary/5 border border-primary/20 ${radius} p-8 text-center`;
    case "stats":      return `bg-muted/30 ${radius} p-6`;
    case "split":      return "bg-background py-8";
    case "full-bleed": return "bg-background py-8";
    default:           return "bg-background py-8"; // plain + unknown
  }
}

function roleClass(role: string, radiusScale: RadiusScale): string {
  const radius = RADIUS_SURFACE_CLASS[radiusScale];
  switch (role) {
    case "headline": return "px-8 pt-12 pb-6 border-b border-border";
    case "content":  return "px-6 py-8";
    case "aside":    return `px-4 py-4 bg-muted/30 ${radius}`;
    case "footer":   return "px-6 pt-4 pb-6 border-t border-border text-sm text-muted-foreground";
    default:         return "px-6 py-8";
  }
}

// Wave 2: density-aware vertical padding (role=undefined path only).
// comfortable = py-8 matches the existing plain/split variant default.
const DENSITY_PY: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "py-4",
  comfortable: "py-8",
  spacious:    "py-12",
};

// Wave 2: elevation-aware border/shadow (role=undefined path only).
// layered = shadow-sm matches existing feature variant; plain variant has no shadow.
// For the token-aware fallback path we apply the elevation class alongside bg-background.
const ELEVATION_CLASS: Record<"flat" | "bordered" | "layered" | "floating", string> = {
  flat:     "",
  bordered: "border border-border",
  layered:  "shadow-sm",
  floating: "shadow-lg",
};

export interface SectionProps extends SectionPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
  /** Schema-supplied class hook — appended to the computed class string. */
  className?: string;
  /** data-* attributes flow through validateProps; spread onto the root element. */
  [key: string]: unknown;
}

export function Section(props: SectionProps) {
  const { variant, title, subtitle, anchor, role, illustration, style, children } = props;
  const callerClass = typeof props.className === "string" ? props.className : undefined;
  const dataAttrs = dataAttrProps(props as Record<string, unknown>);
  // __illustrationBasePath is a private prop injected at the registry layer
  // so the scaffold preview can serve bundled SVGs from
  // /p/<projectId>/illustrations/<slug>.svg. Standalone apps omit it.
  const illustrationBasePath = (props as { __illustrationBasePath?: string })
    .__illustrationBasePath;

  const density = useDensity();
  const elevation = useElevation();
  const radiusScale = useRadiusScale();

  // When role is explicitly provided (non-undefined), use role-based class.
  // When role is undefined:
  //   - default tokens (comfortable + layered) → fall through to variant-driven path (zero drift)
  //   - non-default tokens → use token-aware path
  let wrapClass: string;
  if (role) {
    wrapClass = roleClass(role, radiusScale);
  } else if (density === "comfortable" && elevation === "layered") {
    // Default token values → preserve existing variant-driven behavior exactly.
    wrapClass = variantClass(variant, radiusScale);
  } else {
    // Non-default token values → token-aware path.
    // Base: bg-background + density-driven py; elevation class appended.
    const py = DENSITY_PY[density];
    const elClass = ELEVATION_CLASS[elevation];
    wrapClass = ["bg-background", py, elClass].filter(Boolean).join(" ");
  }
  const hasIllustration = !!illustration?.slug;
  const header = (title || subtitle) && (
    // Use the platform type-scale (Tier S) — section titles are smaller
    // than page-titles by design so the hierarchy reads page → section →
    // card without ambiguity. Editing once in tailwind.config.ts ripples
    // platform-wide.
    <header className="mb-2">
      {title && (
        <h2 className="text-section-title text-foreground">{title}</h2>
      )}
      {subtitle && (
        <p className="text-body text-muted-foreground mt-1.5">{subtitle}</p>
      )}
    </header>
  );
  const sectionBody = hasIllustration && illustration ? (
    // Illustration mode — side-by-side grid. Enables the canonical login
    // split layout: illustration on one side, children form on the other.
    <div className="grid gap-8 md:grid-cols-2 md:items-center">
      <IllustrationResolver
        slug={illustration.slug}
        alt={illustration.alt ?? ""}
        basePath={illustrationBasePath ?? "/illustrations"}
        className="max-w-md w-full h-auto justify-self-center"
      />
      <div>
        {header}
        <div>{children}</div>
      </div>
    </div>
  ) : (
    <>
      {header}
      <div>{children}</div>
    </>
  );

  // full-bleed structural inline styles applied before user overrides so the
  // user style slot can still win if needed.
  const breakoutStyle: React.CSSProperties =
    variant === "full-bleed" ? FULL_BLEED_STYLE : {};

  // When style.background is present, an inner SurfaceBackground carries the
  // gradient/solid backdrop, clipped to the section's existing radius via
  // rounded-[inherit]. The outer <section> still owns layout chrome
  // (padding, border, shadow) and stays a <section> for semantics. When no
  // background, render directly to avoid an extra wrapper div.
  return (
    <section
      id={anchor}
      className={withCallerClass(wrapClass, callerClass)}
      data-variant={variant}
      data-role={role}
      style={{ ...breakoutStyle, ...resolveStyleNoBackground(style) }}
      {...useMotion(style?.motion)}
      {...dataAttrs}
    >
      {style?.background ? (
        <SurfaceBackground
          background={style.background}
          className="rounded-[inherit]"
        >
          {sectionBody}
        </SurfaceBackground>
      ) : (
        sectionBody
      )}
    </section>
  );
}
