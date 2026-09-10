"use client";
import * as React from "react";
import type { FocusRingPropsType } from "./FocusRing.schema";

export interface FocusRingProps extends FocusRingPropsType {
  children?: React.ReactNode;
}

/**
 * FocusRing — Spec E Wave 2. Wraps children in a span whose focused
 * descendant carries an outline built from the app's focus tokens.
 *
 * IT USED TO DRAW NO RING AT ALL.
 * -------------------------------
 * The custom properties were set and inherited correctly — a child button
 * really did compute `--focus-ring-color: #ff0000` — and **nothing consumed
 * them**. The rule that reads them lives in `style/focus-ring.css`, which
 * reaches an app only through `interactions_css_inject.py` behind the
 * `FORGE_POLISH_A11Y` flag. An audit scanned all 246 CSS rules in the editor
 * document for `focus-ring` and found zero, and grepped a real generated app
 * for `--focus-ring-color` and found none: the component was dead on the canvas
 * AND dead in the shipped app. That is worse than not shipping it, because an
 * author who drops one believes the page now meets WCAG 2.4.7.
 *
 * A component cannot depend on a flag-gated backend CSS pass for the one thing
 * it exists to do, so it carries its own rule. The `<style>` below is emitted
 * once per FocusRing instance, is scoped to `[data-forge-focus-ring]` so it
 * cannot leak, and is written so the injected stylesheet — when it IS present —
 * simply sets the same custom properties higher up and nothing conflicts.
 *
 * The outline uses ``outline`` (not ``box-shadow``) so it follows the element's
 * actual shape and doesn't require the child to have ``position: relative``.
 */

/** Scoped, self-contained — the ring works with no build step and no flag. */
const RING_CSS = `
[data-forge-focus-ring] > *:focus-visible,
[data-forge-focus-ring]:focus-within > *:focus-visible {
  outline: var(--focus-ring-width, 2px) solid var(--focus-ring-color, #2563eb);
  outline-offset: var(--focus-ring-offset, 2px);
}`;
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
      <style dangerouslySetInnerHTML={{ __html: RING_CSS }} />
      {children}
    </span>
  );
}
