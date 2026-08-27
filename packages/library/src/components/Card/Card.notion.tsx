// packages/library/src/components/Card/Card.notion.tsx
import * as React from "react";
import type { ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Notion-register Card variant.
 *
 * Visual language:
 *   - No border, no shadow (elevation.flat) — content-forward
 *   - Generous padding (density.spacious)
 *   - Rounded-lg (radius.round 12px)
 *   - Soft hover-state via subtle background shift (muted/30)
 *   - Serif typography via token inheritance
 *
 * Props mirror the default Card exactly — drop-in variant.
 */

type SchemaDensity = "tight" | "regular" | "loose";
type SchemaElevation = "none" | "sm" | "md" | "lg";

type CardNotionProps = {
  title?: string;
  footer?: string;
  /** Accepted for interface parity; Notion variant always uses flat treatment. */
  elevation?: SchemaElevation;
  /** Accepted for interface parity; Notion variant always uses spacious padding. */
  density?: SchemaDensity;
  children?: ReactNode;
  style?: StyleSlotT;
};

const CARD = "rounded-lg bg-card text-card-foreground hover:bg-muted/30 transition-colors";
const TITLE = "px-6 pt-5 pb-2 text-base font-semibold";
const BODY = "px-6 py-4";
const FOOTER = "px-6 py-3 text-sm text-muted-foreground";

export function CardNotion({ title, footer, children, style }: CardNotionProps) {
  const motionProps = useMotion(style?.motion);
  return (
    <div data-card="" className={CARD} style={resolveStyle(style)} {...motionProps}>
      {title && <div data-slot="header" className={TITLE}>{title}</div>}
      <div className={BODY}>{children}</div>
      {footer && <div className={FOOTER}>{footer}</div>}
    </div>
  );
}
