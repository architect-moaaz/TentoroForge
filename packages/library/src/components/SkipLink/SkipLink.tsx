"use client";
import * as React from "react";
import type { SkipLinkPropsType } from "./SkipLink.schema";

export interface SkipLinkProps extends SkipLinkPropsType {}

// Visually-hidden until focused. Uses the WCAG-safe pattern (sr-only) —
// on focus we swap to a visible fixed position at top-left. Inline
// styles so the primitive works whether or not Tailwind ships in the
// consumer app.
const HIDDEN: React.CSSProperties = {
  position: "absolute",
  width: "1px",
  height: "1px",
  padding: 0,
  margin: "-1px",
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

const VISIBLE: React.CSSProperties = {
  position: "fixed",
  top: "0.75rem",
  left: "0.75rem",
  zIndex: 9999,
  padding: "0.5rem 1rem",
  borderRadius: "var(--radius-md, 0.375rem)",
  background: "var(--color-background, #ffffff)",
  color: "var(--color-foreground, #111827)",
  boxShadow:
    "0 0 0 var(--focus-ring-width, 2px) var(--focus-ring-color, currentColor), 0 2px 8px rgba(0,0,0,0.15)",
  textDecoration: "none",
  fontSize: "0.875rem",
  fontWeight: 600,
};

/**
 * SkipLink — Spec E Wave 2. Renders an anchor that stays hidden until
 * the user tabs to it, at which point it becomes a visible "Skip to
 * main content" button. Activating it jumps focus to the target
 * landmark (default ``#main``), bypassing the nav.
 */
export function SkipLink({
  target = "main",
  label = "Skip to main content",
  className,
}: SkipLinkProps): React.ReactElement {
  const [focused, setFocused] = React.useState(false);
  const hash = target.startsWith("#") ? target : `#${target}`;
  const id = target.startsWith("#") ? target.slice(1) : target;

  // We handle activation ourselves so we can move focus (not just the
  // caret hash) — a plain `href` alone updates the URL but does not
  // move keyboard focus to the target in every browser.
  const onClick = React.useCallback(
    (e: React.MouseEvent<HTMLAnchorElement>) => {
      const el =
        typeof document !== "undefined" ? document.getElementById(id) : null;
      if (el) {
        e.preventDefault();
        // Make the landmark focusable if it isn't already (main isn't
        // by default). tabIndex="-1" keeps it out of the tab order but
        // allows programmatic focus.
        if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
        try {
          el.focus();
        } catch {
          /* ignore */
        }
        // Also scroll into view for sighted keyboard users.
        try {
          el.scrollIntoView({ block: "start" });
        } catch {
          /* ignore */
        }
      }
    },
    [id],
  );

  return (
    <a
      href={hash}
      onClick={onClick}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={focused ? VISIBLE : HIDDEN}
      className={className}
      data-forge-skip-link=""
    >
      {label}
    </a>
  );
}
