"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { TagPropsType } from "./Tag.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

// default/primary use semantic theme tokens; status variants use inline hex to
// honour the library theming contract (no raw Tailwind palette classes).
const VARIANT_CLASS: Record<string, string> = {
  default: "bg-muted text-foreground",
  primary: "bg-primary/10 text-primary",
  // Accent — second brand hue (see Badge.tsx for the same rationale).
  // Composer sets `variant="accent"` when a chip should read as a
  // secondary emphasis rather than a primary CTA.
  accent:  "bg-accent text-accent-foreground",
};
const VARIANT_STYLE: Record<string, { background: string; color: string }> = {
  success: { background: "#dcfce7", color: "#166534" },
  warning: { background: "#fef3c7", color: "#92400e" },
  danger:  { background: "#fee2e2", color: "#991b1b" },
};

export interface TagProps extends TagPropsType {
  style?: StyleSlotT;
  onRemove?: () => void;
}

export function Tag({ label, variant = "default", removable, style, onRemove }: TagProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${VARIANT_CLASS[variant] ?? ""}`}
      data-tag=""
      style={{ ...(VARIANT_STYLE[variant] ?? {}), ...resolveStyle(style) }}
      {...useMotion(style?.motion)}
    >
      {label}
      {removable && (
        <button
          type="button"
          aria-label="Remove"
          onClick={onRemove}
          className="ml-0.5 inline-flex h-3.5 w-3.5 items-center justify-center rounded-full hover:bg-black/10"
        >
          ×
        </button>
      )}
    </span>
  );
}
