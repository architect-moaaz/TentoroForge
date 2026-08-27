// packages/library/src/components/Card/Card.linear.tsx
import * as React from "react";
import type { ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Linear-register Card variant.
 *
 * Visual language:
 *   - Subtle hairline border (border-border/60) for boundary affordance —
 *     pure flat (no border at all) renders as a styling void at card-grid
 *     density and people read the page as "broken" even when components
 *     are correctly dispatching.
 *   - Card-surface background (not muted) so the page hierarchy reads
 *     muted-page → card-surface, the Linear pattern.
 *   - Rounded-md (Linear's standard radius — sharper than the default soft)
 *   - Hover lifts border opacity for clickable affordance.
 *   - Simple section divider between title and body.
 *   - `space-y-3` inside the body to give title/status/desc/avatar/meta
 *     proper vertical rhythm — without this the rows are cramped.
 *
 * Props mirror the default Card exactly — drop-in variant.
 */

type SchemaDensity = "tight" | "regular" | "loose";
type SchemaElevation = "none" | "sm" | "md" | "lg";

type CardLinearProps = {
  title?: string;
  footer?: string;
  /** Accepted for interface parity; Linear variant always uses flat treatment. */
  elevation?: SchemaElevation;
  /** Accepted for interface parity; Linear variant always uses compact padding. */
  density?: SchemaDensity;
  children?: ReactNode;
  style?: StyleSlotT;
};

export function CardLinear({ title, footer, children, style }: CardLinearProps) {
  const motionProps = useMotion(style?.motion);
  return (
    <div
      data-card=""
      // `h-full` makes every card in a Grid row stretch to the tallest one
      // — without it, cards with shorter titles render at half the height
      // of cards with two-line titles, breaking the grid rhythm.
      // `flex flex-col` then lets children (especially the schema's footer
      // row — priority pill + View button) sit at the natural bottom via
      // `flex-1` on the body section below.
      // `rounded-lg` (slightly softer than rounded-md) reads as a proper
      // card-grid card; rounded-md looked square at this scale.
      className="bg-card border border-border/60 rounded-xl hover:border-border transition-colors h-full flex flex-col"
      style={resolveStyle(style)}
      {...motionProps}
    >
      {title && <div data-slot="header" className="px-6 py-3 text-caption font-semibold text-foreground border-b border-border/50">{title}</div>}
      <div className="px-6 py-2 text-body space-y-3 flex-1 flex flex-col">{children}</div>
      {footer && <div className="px-6 py-2.5 border-t border-border/50 text-caption text-muted-foreground">{footer}</div>}
    </div>
  );
}
