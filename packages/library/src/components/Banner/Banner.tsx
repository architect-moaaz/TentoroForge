"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { BannerPropsType } from "./Banner.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { formatValue } from "../../utils/formatValue";
import { resolveIcon } from "../../icons";
import { Link } from "../Link/Link";

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

export function Banner({
  variant = "info", title, message, dismissible, icon, action, style, onDismiss,
}: BannerProps) {
  // DISMISSAL IS REMEMBERED AGAINST *THIS* BANNER, NOT AGAINST THE MOUNT.
  //
  // `useState(true)` + `if (!open) return null` meant a dismissed Banner became
  // zero DOM with no way back — in the editor it could not even be selected
  // again, so the only recovery was to notice which node had vanished and
  // re-select it from somewhere else. Keying the dismissal to the banner's
  // authored identity means editing ANY of its props brings it back, which is
  // exactly what an author expects and needs no editor-specific code: in a
  // shipped app the props do not change mid-session, so dismissal behaves
  // precisely as before.
  const identity = `${variant}|${title ?? ""}|${String(message ?? "")}|${dismissible ? 1 : 0}`;
  const [dismissedFor, setDismissedFor] = React.useState<string | null>(null);
  if (dismissedFor === identity) return null;

  const Icon = icon ? resolveIcon(icon) : null;

  return (
    <div role="alert" data-banner="" data-variant={variant}
      className="flex items-start gap-3 border-s-4 px-4 py-3 text-sm"
      style={{ ...(VARIANT[variant] ?? VARIANT.info), ...resolveStyle(style) }} {...useMotion(style?.motion)}>
      {Icon && <Icon size={18} aria-hidden="true" className="mt-0.5 shrink-0" />}
      <div className="flex-1">
        {title && <div className="font-semibold">{formatValue(title as unknown)}</div>}
        <div>{formatValue(message as unknown)}</div>
        {action && (
          // Delegated to Link rather than re-implemented: Link already routes
          // an internal destination through the Navigator (so it resolves under
          // a preview base path), dispatches a workflow through the workflow
          // context, and renders an honest unset state. A page-level
          // notification without a call to action is usually not worth showing,
          // which is what the audit asked for.
          <div className="mt-1.5">
            <Link
              label={action.label}
              navigate={"navigate" in action ? action.navigate : ""}
              workflow={"workflow" in action ? action.workflow : undefined}
              className="font-medium underline underline-offset-2"
            />
          </div>
        )}
      </div>
      {dismissible && (
        <button type="button" aria-label="Dismiss" onClick={() => { setDismissedFor(identity); onDismiss?.(); }}
          className="shrink-0 opacity-70 hover:opacity-100">✕</button>
      )}
    </div>
  );
}
