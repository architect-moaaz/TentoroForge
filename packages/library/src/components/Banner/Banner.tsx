"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { BannerPropsType } from "./Banner.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { formatValue } from "../../utils/formatValue";

export interface BannerProps extends BannerPropsType {
  style?: StyleSlotT;
  onDismiss?: () => void;
}

// Status colors read the app's own --color-* scale (with the old hexes as
// fallbacks) — hardcoded Tailwind-blue banners were byte-identical in every
// generated app regardless of palette.
const VARIANT: Record<string, { background: string; color: string; borderColor: string }> = {
  info:    { background: "var(--color-info-100, #eff6ff)", color: "var(--color-info-800, #1e3a8a)", borderColor: "var(--color-info-200, #bfdbfe)" },
  success: { background: "var(--color-success-100, #f0fdf4)", color: "var(--color-success-800, #14532d)", borderColor: "var(--color-success-200, #bbf7d0)" },
  warning: { background: "var(--color-warning-100, #fffbeb)", color: "var(--color-warning-800, #78350f)", borderColor: "var(--color-warning-200, #fde68a)" },
  error:   { background: "var(--color-error-100, #fef2f2)", color: "var(--color-error-800, #7f1d1d)", borderColor: "var(--color-error-200, #fecaca)" },
};

export function Banner({ variant = "info", title, message, dismissible, style, onDismiss }: BannerProps) {
  const [open, setOpen] = React.useState(true);
  if (!open) return null;
  return (
    <div role="alert" data-banner="" data-variant={variant}
      className="flex items-start gap-3 border-l-4 px-4 py-3 text-sm"
      style={{ ...(VARIANT[variant] ?? VARIANT.info), ...resolveStyle(style) }} {...useMotion(style?.motion)}>
      <div className="flex-1">
        {title && <div className="font-semibold">{formatValue(title as unknown)}</div>}
        <div>{formatValue(message as unknown)}</div>
      </div>
      {dismissible && (
        <button type="button" aria-label="Dismiss" onClick={() => { setOpen(false); onDismiss?.(); }}
          className="shrink-0 opacity-70 hover:opacity-100">✕</button>
      )}
    </div>
  );
}
