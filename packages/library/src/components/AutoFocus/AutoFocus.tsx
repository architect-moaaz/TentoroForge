"use client";
import * as React from "react";
import { useRuntimeArmed } from "@tentoroforge/renderer";
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
  enabled: enabledProp = true,
  selector,
  delayed = true,
  className,
  children,
}: AutoFocusProps): React.ReactElement {
  const rootRef = React.useRef<HTMLSpanElement | null>(null);
  // On the editor canvas this moved the caret INTO the artefact being edited on
  // every page load, so the author's next Space or Enter pressed a button on the
  // canvas. Worse, the effect's deps are `[enabled, selector, delayed]`, so it
  // re-fired on every keystroke in its own SELECTOR text box — typing a selector
  // was a per-keystroke fight for focus with the Properties panel. `enabled:
  // false` is the runtime setting and turning it off here would also turn it off
  // in the generated app. See useRuntimeArmed.
  const enabled = useRuntimeArmed(enabledProp);

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
      // A queued microtask cannot be cancelled, so the old code's cleanup
      // (`if (id !== null) clearTimeout(id)`) was a no-op on every modern
      // browser: an AutoFocus that unmounted in the same tick it mounted still
      // stole focus. A cancelled flag is the only way to call it off.
      let cancelled = false;
      const guarded = () => { if (!cancelled) doFocus(); };
      const id =
        typeof queueMicrotask === "function"
          ? (queueMicrotask(guarded), null)
          : setTimeout(guarded, 0);
      return () => {
        cancelled = true;
        if (id !== null) clearTimeout(id as unknown as number);
      };
    }
    doFocus();
  }, [enabled, selector, delayed]);

  return (
    <span
      ref={rootRef}
      data-forge-autofocus={enabled ? "enabled" : "disabled"}
      data-forge-autofocus-authored={enabledProp ? "enabled" : "disabled"}
      style={{ display: "contents" }}
      className={className}
    >
      {children}
    </span>
  );
}
