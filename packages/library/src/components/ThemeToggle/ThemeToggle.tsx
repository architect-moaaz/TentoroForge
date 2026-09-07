import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { useMotion } from "../../style/useMotion";
import { resolveStyle } from "../../style/resolveStyle";

/**
 * ThemeToggle — Spec C Slice 8 dark-mode primitive.
 *
 * Reads/writes `document.documentElement.dataset.theme`; persists to
 * localStorage under `storageKey`. On mount, honors saved preference;
 * on first-run, honors `prefers-color-scheme`. SR-friendly: aria-label
 * flips based on current theme.
 *
 * Kept deliberately dependency-free — a <button>, an svg, and a
 * useEffect. No portal, no context. Every generated app can mount it
 * in the shell without extra plumbing.
 */
type Props = {
  lightLabel?: string;
  darkLabel?: string;
  storageKey?: string;
  style?: StyleSlotT;
};

type Theme = "light" | "dark";

function readInitial(storageKey: string): Theme {
  if (typeof window === "undefined") return "light";
  const saved = window.localStorage.getItem(storageKey);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function ThemeToggle({
  lightLabel = "Switch to light mode",
  darkLabel = "Switch to dark mode",
  storageKey = "forge-theme",
  style,
}: Props): React.ReactElement {
  const [theme, setTheme] = React.useState<Theme>("light");
  const rootRef = React.useRef<HTMLButtonElement | null>(null);
  const motion = useMotion(style?.motion);
  const styleProps = resolveStyle(style);

  /**
   * Where this toggle is allowed to write.
   *
   * In the editor the designed page is rendered inside [data-canvas-root], and
   * this component was reaching straight past it: merely DROPPING a ThemeToggle
   * stamped `data-theme` on the *editor's* <html>, and clicking it persisted a
   * preference to the editor's own origin that outlived the session. Scoped to
   * the canvas root, the toggle themes the page being designed and nothing
   * else. In a generated app there is no canvas root, so the target is
   * documentElement and localStorage persistence is unchanged.
   */
  const scopeOf = React.useCallback(
    () => rootRef.current?.closest<HTMLElement>("[data-canvas-root]") ?? null,
    [],
  );

  React.useEffect(() => {
    const scoped = scopeOf();
    const initial = scoped ? "light" : readInitial(storageKey);
    setTheme(initial);
    (scoped ?? document.documentElement).dataset.theme = initial;
  }, [storageKey, scopeOf]);

  const flip = React.useCallback(() => {
    const scoped = scopeOf();
    setTheme((prev) => {
      const next: Theme = prev === "light" ? "dark" : "light";
      (scoped ?? document.documentElement).dataset.theme = next;
      if (!scoped) {
        try {
          window.localStorage.setItem(storageKey, next);
        } catch {
          // localStorage unavailable (private mode, quota) — persist skip is fine.
        }
      }
      return next;
    });
  }, [storageKey, scopeOf]);

  const label = theme === "light" ? darkLabel : lightLabel;

  return (
    <button
      ref={rootRef}
      type="button"
      onClick={flip}
      aria-label={label}
      title={label}
      data-forge-theme-toggle
      data-current-theme={theme}
      {...motion}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 36,
        height: 36,
        borderRadius: "var(--radius-md, 0.375rem)",
        border: "1px solid var(--border, hsl(0 0% 90%))",
        background: "transparent",
        color: "var(--foreground, hsl(0 0% 15%))",
        cursor: "pointer",
        ...styleProps,
      }}
    >
      {theme === "light" ? (
        // Moon (click to go dark)
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
             aria-hidden="true">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      ) : (
        // Sun (click to go light)
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
             aria-hidden="true">
          <circle cx="12" cy="12" r="5" />
          <line x1="12" y1="1" x2="12" y2="3" />
          <line x1="12" y1="21" x2="12" y2="23" />
          <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
          <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
          <line x1="1" y1="12" x2="3" y2="12" />
          <line x1="21" y1="12" x2="23" y2="12" />
          <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
          <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
        </svg>
      )}
    </button>
  );
}
