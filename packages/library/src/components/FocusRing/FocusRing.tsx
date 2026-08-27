"use client";
import * as React from "react";
import type { FocusRingPropsType } from "./FocusRing.schema";

export interface FocusRingProps extends FocusRingPropsType {
  children?: React.ReactNode;
}

/**
 * FocusRing — Spec E Wave 2. Wraps children in a span that carries a
 * ``:focus-visible`` outline reading the app's focus tokens. Zero-
 * runtime — pure CSS. When the parent controls tokens via
 * ``--focus-ring-*`` custom properties (see focus-ring.css injected
 * by ``interactions_css_inject``), the ring adopts them app-wide.
 *
 * The rendered outline uses ``outline`` (not ``box-shadow``) so it
 * follows the element's actual shape and doesn't require the child
 * to have ``position: relative``.
 */
export function FocusRing({
  color,
  width,
  offset,
  className,
  children,
}: FocusRingProps): React.ReactElement {
  const style: React.CSSProperties = {
    // Container is display:contents so it doesn't alter layout at all.
    // The focus-visible target is the child that actually receives
    // focus — CSS below uses `:focus-visible` on the child via the
    // `data-forge-focus-ring` attribute + a scoped rule.
    display: "contents",
  };
  const cssVars: Record<string, string> = {};
  if (color) cssVars["--focus-ring-color"] = color;
  if (typeof width === "number") cssVars["--focus-ring-width"] = `${width}px`;
  if (typeof offset === "number")
    cssVars["--focus-ring-offset"] = `${offset}px`;

  return (
    <span
      data-forge-focus-ring=""
      style={{ ...style, ...(cssVars as React.CSSProperties) }}
      className={className}
    >
      {children}
    </span>
  );
}
