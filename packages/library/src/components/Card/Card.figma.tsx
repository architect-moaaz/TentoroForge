// packages/library/src/components/Card/Card.figma.tsx
import * as React from "react";
import type { ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Figma-register Card variant.
 *
 * Visual language:
 *   - Rounded-2xl, shadow-lg (elevation.floating), overflow-hidden
 *   - Gradient header accent strip (from-primary/10 to secondary/10) when title present
 *   - Bold title on tinted gradient background
 *   - Generous body padding (density.comfortable)
 *   - Subtle muted footer with top border
 *
 * Props mirror the default Card exactly — drop-in variant.
 */

type SchemaDensity = "tight" | "regular" | "loose";
type SchemaElevation = "none" | "sm" | "md" | "lg";

type CardFigmaProps = {
  title?: string;
  footer?: string;
  /** Accepted for interface parity; Figma variant always uses floating elevation. */
  elevation?: SchemaElevation;
  /** Accepted for interface parity; Figma variant always uses comfortable padding. */
  density?: SchemaDensity;
  children?: ReactNode;
  style?: StyleSlotT;
};

const CARD = "rounded-2xl border border-border bg-card text-card-foreground shadow-lg overflow-hidden";
const TITLE = "px-6 py-4 border-b border-border bg-gradient-to-r from-primary/10 to-secondary/10 text-base font-bold";
const BODY = "px-6 py-5";
const FOOTER = "px-6 py-4 border-t border-border bg-muted/30";

export function CardFigma({ title, footer, children, style }: CardFigmaProps) {
  const motionProps = useMotion(style?.motion);
  return (
    <div data-card="" className={CARD} style={resolveStyle(style)} {...motionProps}>
      {title && <div data-slot="header" className={TITLE}>{title}</div>}
      <div className={BODY}>{children}</div>
      {footer && <div className={FOOTER}>{footer}</div>}
    </div>
  );
}
