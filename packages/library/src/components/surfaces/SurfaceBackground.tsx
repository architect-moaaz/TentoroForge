import * as React from "react";
import type { BackgroundT } from "@tentoroforge/schema";
import { backgroundCss, colorValue } from "../../style/resolveStyle";

type GradientBg = {
  type: "linear";
  angle?: number;
  from: string;
  to: string;
};

type SolidBg = string;

/**
 * Accepts three shapes:
 *   - Library-internal gradient ({ type: "linear", from, to, angle? }) with literal CSS colors
 *   - Schema `BackgroundT` discriminated union (type: "solid" | "gradient" | "image" | "pattern")
 *     with design-token references — resolved via `backgroundCss`
 *   - Plain CSS string (e.g. "#ff00ff" or "var(--token-color-surface-0)")
 *   - undefined — no inline background
 */
export type SurfaceBg = GradientBg | BackgroundT | SolidBg | undefined;

interface Props extends React.HTMLAttributes<HTMLDivElement> {
  background?: SurfaceBg;
  children?: React.ReactNode;
}

function isLibraryGradient(b: SurfaceBg): b is GradientBg {
  return !!b && typeof b === "object" && (b as GradientBg).type === "linear";
}

function isSchemaBackground(b: SurfaceBg): b is BackgroundT {
  if (!b || typeof b !== "object") return false;
  const t = (b as { type?: string }).type;
  return t === "solid" || t === "gradient" || t === "image" || t === "pattern";
}

/**
 * Renders a backdrop layer based on a design-token background descriptor.
 *
 * - Library gradient ({ type: "linear", ... }) → CSS linear-gradient (default 135deg)
 * - Schema BackgroundT (solid/gradient/image/pattern) → CSS via shared `backgroundCss`
 * - Solid color string                              → CSS background color
 * - undefined                                       → no inline background
 *
 * Composes with the consumer's own className for borders, padding, radius.
 */
export function SurfaceBackground({ background, style, children, ...rest }: Props) {
  let bgStyle: React.CSSProperties = {};
  if (isLibraryGradient(background)) {
    bgStyle = {
      background: `linear-gradient(${background.angle ?? 135}deg, ${background.from}, ${background.to})`,
    };
  } else if (isSchemaBackground(background)) {
    bgStyle = { background: backgroundCss(background) };
  } else if (typeof background === "string") {
    // Through `colorValue`, NOT verbatim. The Style tab's Background dropdown
    // writes bare token refs ("color.primary.500"), and passing one straight to
    // CSS produced `background: color.primary.500` — not valid CSS, discarded
    // by the browser, fill never painted, nothing in the console. The two
    // object branches above already resolve tokens via backgroundCss; this
    // branch was the one that did not, which is why Background looked dead on
    // exactly the three SurfaceBackground consumers: Card, Hero and Section
    // (docs/editor-audit/panels.md, "Style — Background is DEAD on
    // Card / Hero / Section").
    bgStyle = { background: colorValue(background) };
  }
  return (
    <div style={{ ...bgStyle, ...style }} {...rest}>
      {children}
    </div>
  );
}
