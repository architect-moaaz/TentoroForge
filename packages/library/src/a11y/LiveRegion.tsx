"use client";

import * as React from "react";
import { subscribe } from "./announcer";

/**
 * LiveRegion — Spec E Wave 2. Mount once at the app root (usually in
 * the generated shell). Renders two `aria-live` divs (polite +
 * assertive) that display any text pushed through `announce()`.
 *
 * The divs are visually hidden with an inline sr-only pattern so we
 * stay decoupled from Tailwind availability — the generated app's
 * globals.css may or may not carry the `sr-only` utility depending on
 * the theme, and this primitive needs to work either way.
 *
 * Nesting is safe: multiple mounts all subscribe to the same store, so
 * every LiveRegion instance displays the same text. Screen readers
 * read the first live region they encounter — duplicate mounts don't
 * cause duplicate announcements at the SR level.
 */

// Visually-hidden inline style — WCAG-safe (kept in a11y tree, unlike
// display:none / visibility:hidden). Not `overflow:hidden` alone; the
// full pattern below is what SRs consistently pick up across engines.
const SR_ONLY: React.CSSProperties = {
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

export interface LiveRegionProps {
  /**
   * Extra class applied to both live regions — mostly for test hooks.
   * Do NOT use this to un-hide the region; SRs need it out of the
   * visible flow.
   */
  className?: string;
}

export function LiveRegion({ className }: LiveRegionProps): React.ReactElement {
  const [polite, setPolite] = React.useState<string>("");
  const [assertive, setAssertive] = React.useState<string>("");

  React.useEffect(() => {
    return subscribe((text, urgency) => {
      if (urgency === "polite") setPolite(text);
      else setAssertive(text);
    });
  }, []);

  return (
    <>
      <div
        aria-live="polite"
        aria-atomic="true"
        role="status"
        style={SR_ONLY}
        className={className}
        data-forge-live="polite"
      >
        {polite}
      </div>
      <div
        aria-live="assertive"
        aria-atomic="true"
        role="alert"
        style={SR_ONLY}
        className={className}
        data-forge-live="assertive"
      >
        {assertive}
      </div>
    </>
  );
}
