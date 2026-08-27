import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { useMotion } from "../../style/useMotion";
import { resolveStyle } from "../../style/resolveStyle";

type Props = {
  placeholder?: string;
  workflow: string;
  debounceMs?: number;
  style?: StyleSlotT;
};

/**
 * GlobalSearch — Spec C Slice 7 app-wide search input.
 *
 * Debounces keystrokes and fires the configured workflow with
 * { query: string }. Cmd+K / Ctrl+K focuses the input from anywhere.
 * Presentation-only — the workflow decides how to search + render
 * results (a Dialog or a full /search route).
 */
export function GlobalSearch({
  placeholder = "Search…", workflow, debounceMs = 200, style,
}: Props): React.ReactElement {
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const motion = useMotion(style?.motion);
  const styleProps = resolveStyle(style);

  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isCmdK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k";
      if (isCmdK) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const fire = React.useCallback((q: string) => {
    // Dispatch as a DOM event; renderer's workflow-dispatch layer picks it up.
    // (Same convention buttons use via [data-forge-workflow].)
    const el = document.createElement("button");
    el.setAttribute("data-forge-workflow", workflow);
    el.setAttribute("data-forge-workflow-args", JSON.stringify({ query: q }));
    el.style.display = "none";
    document.body.appendChild(el);
    el.click();
    setTimeout(() => document.body.removeChild(el), 0);
  }, [workflow]);

  const onChange = React.useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value;
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => fire(q), debounceMs);
  }, [debounceMs, fire]);

  return (
    <div
      data-forge-global-search
      {...motion}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 10px",
        border: "1px solid var(--border, hsl(0 0% 90%))",
        borderRadius: "var(--radius-md, 0.375rem)",
        background: "var(--background, white)",
        minWidth: 240,
        ...styleProps,
      }}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="2" strokeLinecap="round"
           strokeLinejoin="round" aria-hidden="true"
           style={{ color: "var(--muted-foreground, hsl(0 0% 45%))" }}>
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
      <input
        ref={inputRef}
        type="search"
        role="searchbox"
        placeholder={placeholder}
        onChange={onChange}
        aria-label="Global search"
        style={{
          border: "none",
          outline: "none",
          background: "transparent",
          flex: 1,
          fontSize: "0.875rem",
          color: "var(--foreground, hsl(0 0% 15%))",
        }}
      />
      <kbd style={{
        fontSize: "0.688rem",
        padding: "2px 6px",
        border: "1px solid var(--border, hsl(0 0% 90%))",
        borderRadius: 3,
        color: "var(--muted-foreground, hsl(0 0% 45%))",
      }}>⌘K</kbd>
    </div>
  );
}
