"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { AccordionPropsType } from "./Accordion.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useDensity, useRadiusScale } from "../../theme/tokens-context";

/**
 * Accordion — collapsible panel group. mode="single" closes other panels
 * when one opens; mode="multi" lets multiple be open simultaneously.
 *
 * Children must be AccordionPanel components. Each panel receives its
 * expansion state + toggle callback via React context. Renders with
 * shadcn-style chrome so the project's globals.css governs the look.
 */
export interface AccordionProps extends AccordionPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

interface AccordionContextValue {
  mode: "single" | "multi";
  isOpen(value: string): boolean;
  toggle(value: string): void;
}

const AccordionContext = React.createContext<AccordionContextValue | null>(null);

export function useAccordion(): AccordionContextValue {
  const ctx = React.useContext(AccordionContext);
  if (!ctx) throw new Error("AccordionPanel must be a descendant of Accordion");
  return ctx;
}

const ACCORDION_GAP: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "gap-0",
  comfortable: "gap-0",
  spacious:    "gap-2",
};

export function Accordion({ mode, defaultOpen = [], style, children }: AccordionProps) {
  const [openSet, setOpenSet] = React.useState<Set<string>>(() => new Set(defaultOpen));
  const density = useDensity();
  const radiusScale = useRadiusScale();

  const ctx: AccordionContextValue = React.useMemo(() => ({
    mode,
    isOpen: (v) => openSet.has(v),
    toggle: (v) => setOpenSet((prev) => {
      const next = new Set(prev);
      if (next.has(v)) next.delete(v);
      else if (mode === "single") { next.clear(); next.add(v); }
      else next.add(v);
      return next;
    }),
  }), [mode, openSet]);

  return (
    <AccordionContext.Provider value={ctx}>
      <div
        className={`flex flex-col ${RADIUS_SURFACE_CLASS[radiusScale]} border bg-card text-card-foreground divide-y divide-border overflow-hidden ${ACCORDION_GAP[density]}`}
        data-accordion-mode={mode}
        style={resolveStyle(style)}
        {...useMotion(style?.motion)}
      >
        {children}
      </div>
    </AccordionContext.Provider>
  );
}
