import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { FeatureCardPropsType } from "./FeatureCard.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useRadiusScale } from "../../theme/tokens-context";
import { looksLikeIconName, resolveIcon } from "../../icons";

/**
 * FeatureCard — icon + title + description block, optional CTA. Two layouts:
 *   icon-top:  icon above the title (default)
 *   icon-left: icon to the left of the title/description
 *
 * Renders with shadcn/Tailwind utilities so the project's globals.css
 * governs the look.
 */
export interface FeatureCardProps extends FeatureCardPropsType {
  style?: StyleSlotT;
}

export function FeatureCard({ title, description, icon, cta, layout, style }: FeatureCardProps) {
  const isLeft = layout === "icon-left";
  const radiusScale = useRadiusScale();
  // `icon` is an icon NAME ("Sparkles"), not text. The span was self-closing and
  // never called resolveIcon, so a correctly-typed Lucide name painted an empty
  // tinted square. Same treatment IconButton got: resolve the name, render a
  // dashed placeholder carrying the offending value when it resolves to
  // nothing, and pass a non-name string ("→", "🗑") straight through as the
  // glyph the author typed on purpose.
  const Icon = icon ? resolveIcon(icon) : null;
  const glyphPx = isLeft ? 20 : 24;
  return (
    <article
      className={`bg-card text-card-foreground ${RADIUS_SURFACE_CLASS[radiusScale]} border shadow-sm p-6 flex ${isLeft ? "flex-row gap-4" : "flex-col gap-3"}`}
      data-feature-layout={layout}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {icon && (
        <span
          className={`inline-flex items-center justify-center rounded-md bg-primary/10 text-primary ${isLeft ? "h-10 w-10 shrink-0" : "h-12 w-12"}`}
          data-icon={icon}
          aria-hidden="true"
        >
          {Icon
            ? <Icon size={glyphPx} strokeWidth={1.5} aria-hidden="true" />
            : looksLikeIconName(icon)
              ? (
                <span
                  data-unresolved-icon={icon}
                  title={`Unknown icon "${icon}"`}
                  style={{
                    display: "inline-block",
                    width: glyphPx,
                    height: glyphPx,
                    borderRadius: 4,
                    border: "1px dashed currentColor",
                    opacity: 0.5,
                  }}
                />
              )
              : icon}
        </span>
      )}
      <div className="flex flex-col gap-1.5 min-w-0">
        <h3 className="text-base font-semibold tracking-tight text-foreground">{title}</h3>
        <p className="text-sm text-muted-foreground leading-relaxed">{description}</p>
        {cta && (
          <a
            className="text-sm font-medium text-primary hover:underline mt-2 inline-flex items-center gap-1"
            href={cta.href}
          >
            {cta.label} →
          </a>
        )}
      </div>
    </article>
  );
}
