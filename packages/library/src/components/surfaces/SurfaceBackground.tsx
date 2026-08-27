import * as React from "react";
import type { BackgroundT } from "@tentoroforge/schema";
import { backgroundCss } from "../../style/resolveStyle";

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
    bgStyle = { background };
  }
  return (
    <div style={{ ...bgStyle, ...style }} {...rest}>
      {children}
    </div>
  );
}
