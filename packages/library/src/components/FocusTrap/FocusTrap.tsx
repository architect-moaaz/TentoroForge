"use client";
import * as React from "react";
import type { FocusTrapPropsType } from "./FocusTrap.schema";

export interface FocusTrapProps extends FocusTrapPropsType {
  children?: React.ReactNode;
}

/**
 * FocusTrap — Spec E Wave 2. Contains keyboard focus inside its
 * subtree. Handles Tab / Shift-Tab wrap-around, initial focus of the
 * first focusable descendant, and focus restoration on unmount.
 *
 * Intentionally lightweight — no third-party trap library. Modal /
 * Drawer / Popover host their own dismissal keys (Escape); this
 * primitive only owns focus containment.
 */

// Focusable-element selector — matches what browsers themselves treat as
// tab-stops. `[tabindex="-1"]` is deliberately excluded so programmatic-
// only nodes (e.g. scroll containers) don't steal the trap.
const FOCUSABLE_SELECTOR = [
  "a[href]",
  "area[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "iframe",
  "audio[controls]",
  "video[controls]",
  "[contenteditable]:not([contenteditable='false'])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function _focusables(root: HTMLElement): HTMLElement[] {
  const nodes = Array.from(
    root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  );
  return nodes.filter(
    (n) =>
      !n.hasAttribute("disabled") &&
      n.tabIndex !== -1 &&
      // Cheap visibility check — jsdom doesn't compute layout so we
      // don't gate on offsetParent alone.
      n.getAttribute("aria-hidden") !== "true",
  );
}

export function FocusTrap({
  active = true,
  autoFocus = true,
  restoreFocus = true,
  className,
  children,
}: FocusTrapProps): React.ReactElement {
  const rootRef = React.useRef<HTMLDivElement | null>(null);
  const previouslyFocused = React.useRef<HTMLElement | null>(null);

  // Initial focus + restore on unmount / deactivate.
  React.useEffect(() => {
    if (!active) return;
    previouslyFocused.current =
      (typeof document !== "undefined"
        ? (document.activeElement as HTMLElement | null)
        : null);
    const root = rootRef.current;
    if (autoFocus && root) {
      const focusables = _focusables(root);
      const target = focusables[0] ?? root;
      // Root itself may not be focusable; give it a temporary -1 tabindex
      // as a safe fallback so screen readers still land inside the trap.
      if (target === root && !root.hasAttribute("tabindex")) {
        root.setAttribute("tabindex", "-1");
      }
      try {
        target.focus();
      } catch {
        /* ignore focus errors in headless environments */
      }
    }
    return () => {
      if (!restoreFocus) return;
      const prev = previouslyFocused.current;
      if (prev && typeof prev.focus === "function") {
        try {
          prev.focus();
        } catch {
          /* ignore */
        }
      }
    };
  }, [active, autoFocus, restoreFocus]);

  // Tab / Shift-Tab wrap-around.
  const onKeyDown = React.useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (!active) return;
      if (e.key !== "Tab") return;
      const root = rootRef.current;
      if (!root) return;
      const focusables = _focusables(root);
      if (focusables.length === 0) {
        // Nothing focusable inside — keep focus pinned to the root.
        e.preventDefault();
        root.focus();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const activeEl =
        typeof document !== "undefined"
          ? (document.activeElement as HTMLElement | null)
          : null;
      if (e.shiftKey && activeEl === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && activeEl === last) {
        e.preventDefault();
        first.focus();
      }
    },
    [active],
  );

  return (
    <div
      ref={rootRef}
      data-forge-focus-trap={active ? "active" : "inactive"}
      onKeyDown={onKeyDown}
      className={className}
    >
      {children}
    </div>
  );
}
