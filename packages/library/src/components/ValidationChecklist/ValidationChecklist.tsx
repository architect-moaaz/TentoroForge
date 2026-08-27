"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ValidationChecklistPropsType } from "./ValidationChecklist.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface ValidationChecklistProps extends ValidationChecklistPropsType {
  style?: StyleSlotT;
}

export function ValidationChecklist({
  items = [],
  orientation = "vertical",
  className,
  style,
}: ValidationChecklistProps) {
  const rootCls =
    orientation === "horizontal"
      ? "flex flex-wrap gap-x-6 gap-y-2"
      : "flex flex-col gap-2";

  return (
    <div
      data-validation-checklist=""
      data-orientation={orientation}
      className={rootCls}
      style={resolveStyle(style)}
      {...useMotion((style as any)?.motion)}
    >
      {items.map((item, idx) => (
        <div
          key={idx}
          data-valid={String(item.valid)}
          className="flex items-center gap-1.5 text-sm"
        >
          <span
            style={{ color: item.valid ? "#16a34a" : "#dc2626" }}
            aria-hidden="true"
          >
            {item.valid ? "✓" : "✗"}
          </span>
          <span className="text-foreground">{item.label}</span>
        </div>
      ))}
    </div>
  );
}
