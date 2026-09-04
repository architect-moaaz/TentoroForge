"use client";
import * as React from "react";
import { useAccordion } from "./Accordion";

/**
 * AccordionPanel — single collapsible row inside an Accordion. Renders with
 * shadcn-style chrome (rotating chevron indicator, hover states).
 */
export interface AccordionPanelProps {
  value: string;
  label: string;
  children?: React.ReactNode;
}

export function AccordionPanel({ value, label, children }: AccordionPanelProps) {
  const { isOpen, toggle } = useAccordion();
  const open = isOpen(value);
  return (
    <div data-accordion-value={value}>
      <button
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-sm font-medium text-foreground hover:bg-muted/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
        data-accordion-open={open ? "true" : "false"}
        aria-expanded={open}
        type="button"
        onClick={() => toggle(value)}
      >
        <span className="text-start">{label}</span>
        <span
          className="text-muted-foreground transition-transform shrink-0"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
          aria-hidden="true"
        >
          ⌄
        </span>
      </button>
      <div
        className="px-4 pb-4 pt-1 text-sm text-muted-foreground leading-relaxed"
        data-accordion-body=""
        data-accordion-open={open ? "true" : "false"}
        hidden={!open}
      >
        {children}
      </div>
    </div>
  );
}
