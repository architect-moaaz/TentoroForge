// packages/library/src/components/Card/Card.workday.tsx
import * as React from "react";
import type { ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Workday-register Card variant.
 *
 * Visual language:
 *   - Border-only treatment — no shadow (elevation.bordered)
 *   - Section borders separating title / body / footer (data-table feel)
 *   - Hover-state primary-tinted border edge
 *   - Compact padding throughout (density.compact)
 *
 * Props mirror the default Card exactly so it is a drop-in variant.
 */

type SchemaDensity = "tight" | "regular" | "loose";
type SchemaElevation = "none" | "sm" | "md" | "lg";

type CardWorkdayProps = {
  title?: string;
  footer?: string;
  /** Schema-level elevation — accepted for interface parity; Workday variant always uses bordered treatment. */
  elevation?: SchemaElevation;
  /** Schema-level density — accepted for interface parity; Workday variant always uses compact padding. */
  density?: SchemaDensity;
  children?: ReactNode;
  style?: StyleSlotT;
};

const CARD =
  "border border-border bg-card text-card-foreground transition-colors hover:border-primary/40";
const TITLE =
  "border-b border-border px-5 py-3 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground";
const BODY = "px-5 py-4";
const FOOTER = "border-t border-border px-5 py-3 text-sm text-muted-foreground";

export function CardWorkday({
  title,
  footer,
  children,
  style,
}: CardWorkdayProps) {
  const motionProps = useMotion(style?.motion);
  return (
    <div
      data-card=""
      className={CARD}
      style={resolveStyle(style)}
      {...motionProps}
    >
      {title && <div data-slot="header" className={TITLE}>{title}</div>}
      <div className={BODY}>{children}</div>
      {footer && <div className={FOOTER}>{footer}</div>}
    </div>
  );
}
