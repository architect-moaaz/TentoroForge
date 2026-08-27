// packages/library/src/components/Card/Card.stripe.tsx
import * as React from "react";
import type { ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Stripe-register Card variant.
 *
 * Visual language:
 *   - Soft border + shadow-sm + rounded-md (elevation.layered, radius.soft)
 *   - Optional gradient header strip when title present (primary/5 to transparent)
 *   - Generous padding (density.comfortable)
 *   - Clean footer with top separator
 *
 * Props mirror the default Card exactly — drop-in variant.
 */

type SchemaDensity = "tight" | "regular" | "loose";
type SchemaElevation = "none" | "sm" | "md" | "lg";

type CardStripeProps = {
  title?: string;
  footer?: string;
  /** Accepted for interface parity; Stripe variant always uses layered treatment. */
  elevation?: SchemaElevation;
  /** Accepted for interface parity; Stripe variant always uses comfortable padding. */
  density?: SchemaDensity;
  children?: ReactNode;
  style?: StyleSlotT;
};

const CARD = "rounded-md border border-border bg-card text-card-foreground shadow-sm";
const TITLE = "px-5 py-3 border-b border-border bg-gradient-to-r from-primary/5 to-transparent text-sm font-semibold";
const BODY = "px-5 py-4";
const FOOTER = "px-5 py-3 border-t border-border text-sm text-muted-foreground";

export function CardStripe({ title, footer, children, style }: CardStripeProps) {
  const motionProps = useMotion(style?.motion);
  return (
    <div data-card="" className={CARD} style={resolveStyle(style)} {...motionProps}>
      {title && <div data-slot="header" className={TITLE}>{title}</div>}
      <div className={BODY}>{children}</div>
      {footer && <div className={FOOTER}>{footer}</div>}
    </div>
  );
}
