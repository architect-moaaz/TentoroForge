"use client";
import * as React from "react";
import type { AutoFocusPropsType } from "./AutoFocus.schema";

export interface AutoFocusProps extends AutoFocusPropsType {
  children?: React.ReactNode;
}

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[contenteditable]:not([contenteditable='false'])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

/**
 * AutoFocus — Spec E Wave 2. On mount, moves keyboard focus to the
 * first focusable descendant (or the first match of ``selector`` when
 * provided). No-op when ``enabled`` is false.
 *
 * Rendered as a display:contents span so it doesn't affect layout.
 */
export function AutoFocus({
  enabled = true,
  selector,
  delayed = true,
  className,
  children,
}: AutoFocusProps): React.ReactElement {
  const rootRef = React.useRef<HTMLSpanElement | null>(null);

  React.useEffect(() => {
    if (!enabled) return;
    const doFocus = () => {
      const root = rootRef.current;
      if (!root) return;
      let target: HTMLElement | null = null;
      if (selector) {
        try {
          target = root.querySelector<HTMLElement>(selector);
        } catch {
          target = null;
        }
      }
      if (!target) {
        target = root.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      }
      if (target) {
        try {
          target.focus();
        } catch {
          /* ignore focus failures in headless envs */
        }
      }
    };
    if (delayed) {
      // Wait one microtask so we out-race browser scroll restoration
      // and any layout-shifting mounts that happen in the same tick.
      const id = queueMicrotask
        ? (queueMicrotask(doFocus), null)
        : setTimeout(doFocus, 0);
      return () => {
        if (id !== null) clearTimeout(id as unknown as number);
      };
    }
    doFocus();
  }, [enabled, selector, delayed]);

  return (
    <span
      ref={rootRef}
      data-forge-autofocus={enabled ? "enabled" : "disabled"}
      style={{ display: "contents" }}
      className={className}
    >
      {children}
    </span>
  );
}
