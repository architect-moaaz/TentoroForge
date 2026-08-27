import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import type { TourStepType } from "./TourOverlay.schema";

type Props = {
  steps: TourStepType[];
  storageKey?: string;
  autoStart?: boolean;
  nextLabel?: string;
  doneLabel?: string;
  skipLabel?: string;
  style?: StyleSlotT;
  className?: string;
};

/**
 * TourOverlay — spotlighted step-by-step onboarding tour.
 *
 * Simple implementation: reads the target selector on each step, uses
 * `getBoundingClientRect()` for position, and floats a popover near
 * it. Escape or Skip dismisses; reaching the last step + clicking
 * Done marks the tour done in localStorage.
 */
export function TourOverlay({
  steps,
  storageKey = "forge-tour-default",
  autoStart = true,
  nextLabel = "Next",
  doneLabel = "Done",
  skipLabel = "Skip",
  style,
  className,
}: Props): React.ReactElement | null {
  const cleanSteps = Array.isArray(steps) ? steps.filter((s) => s?.target && s?.title) : [];
  const [active, setActive] = React.useState<boolean>(false);
  const [stepIdx, setStepIdx] = React.useState<number>(0);
  const [rect, setRect] = React.useState<DOMRect | null>(null);
  const styleProps = resolveStyle(style);

  React.useEffect(() => {
    if (!autoStart || typeof window === "undefined") return;
    let dismissed = false;
    try {
      dismissed = window.localStorage.getItem(storageKey) === "done";
    } catch { /* private-mode / blocked storage */ }
    if (!dismissed && cleanSteps.length > 0) setActive(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (!active) return;
    if (typeof window === "undefined") return;
    const s = cleanSteps[stepIdx];
    if (!s) return;
    const measure = () => {
      const el = document.querySelector(s.target);
      if (el instanceof HTMLElement) {
        setRect(el.getBoundingClientRect());
      } else {
        setRect(null);
      }
    };
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") end();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, stepIdx]);

  const end = () => {
    setActive(false);
    try {
      if (typeof window !== "undefined") {
        window.localStorage.setItem(storageKey, "done");
      }
    } catch { /* ignore */ }
  };

  if (!active || cleanSteps.length === 0) return null;

  const isLast = stepIdx >= cleanSteps.length - 1;
  const step = cleanSteps[stepIdx];

  // Popover placement — default to below the target with a viewport
  // fallback if there isn't room. Coordinates are viewport-based
  // (position: fixed).
  const pop = computePopoverPosition(rect, step.placement);

  return (
    <div
      data-forge-tour-overlay
      className={className}
      role="dialog"
      aria-modal="false"
      aria-label={`Tour step ${stepIdx + 1} of ${cleanSteps.length}: ${step.title}`}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        pointerEvents: "none",
        ...styleProps,
      }}
    >
      {/* Dimmed backdrop — cutout is not attempted to keep the DOM
          light; a soft translucent layer is enough to draw attention. */}
      <div
        aria-hidden
        style={{
          position: "absolute",
          inset: 0,
          background: "rgba(0,0,0,0.35)",
          pointerEvents: "auto",
        }}
        onClick={end}
      />
      {/* Highlight ring */}
      {rect ? (
        <div
          aria-hidden
          style={{
            position: "absolute",
            top: rect.top - 4,
            left: rect.left - 4,
            width: rect.width + 8,
            height: rect.height + 8,
            borderRadius: "var(--radius-md, 0.5rem)",
            boxShadow: "0 0 0 3px var(--primary, hsl(210 60% 45%)), 0 0 0 9999px rgba(0,0,0,0.001)",
            pointerEvents: "none",
          }}
        />
      ) : null}
      {/* Popover */}
      <div
        data-forge-tour-popover
        style={{
          position: "absolute",
          top: pop.top,
          left: pop.left,
          maxWidth: 320,
          padding: 16,
          borderRadius: "var(--radius-md, 0.5rem)",
          background: "var(--card, white)",
          color: "var(--card-foreground, hsl(0 0% 15%))",
          border: "1px solid var(--border, hsl(0 0% 90%))",
          boxShadow: "0 10px 25px rgba(0,0,0,0.15)",
          pointerEvents: "auto",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <h3 style={{ margin: 0, fontSize: "0.9375rem", fontWeight: 600 }}>{step.title}</h3>
          <span style={{ fontSize: "0.75rem", color: "var(--muted-foreground, hsl(0 0% 45%))" }}>
            {stepIdx + 1} / {cleanSteps.length}
          </span>
        </div>
        {step.body ? (
          <p style={{ margin: "8px 0 12px", fontSize: "0.8125rem", color: "var(--muted-foreground, hsl(0 0% 45%))" }}>
            {step.body}
          </p>
        ) : null}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            type="button"
            onClick={end}
            style={{
              padding: "5px 10px",
              borderRadius: "var(--radius-sm, 0.25rem)",
              border: "1px solid var(--border, hsl(0 0% 85%))",
              background: "transparent",
              cursor: "pointer",
              fontSize: "0.8125rem",
            }}
          >
            {skipLabel}
          </button>
          <button
            type="button"
            onClick={() => (isLast ? end() : setStepIdx((i) => i + 1))}
            data-forge-tour-next
            style={{
              padding: "5px 12px",
              borderRadius: "var(--radius-sm, 0.25rem)",
              border: "none",
              background: "var(--primary, hsl(210 60% 45%))",
              color: "var(--primary-foreground, white)",
              cursor: "pointer",
              fontSize: "0.8125rem",
            }}
          >
            {isLast ? doneLabel : nextLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function computePopoverPosition(
  rect: DOMRect | null,
  placement: TourStepType["placement"] = "auto",
): { top: number; left: number } {
  if (typeof window === "undefined") return { top: 20, left: 20 };
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (!rect) return { top: Math.max(20, vh / 2 - 100), left: Math.max(20, vw / 2 - 160) };
  const gap = 12;
  const preferred = placement === "auto"
    ? (rect.bottom + 220 < vh ? "bottom" : "top")
    : placement;
  if (preferred === "bottom") return { top: rect.bottom + gap, left: clamp(rect.left, 12, vw - 332) };
  if (preferred === "top")    return { top: Math.max(12, rect.top - 220), left: clamp(rect.left, 12, vw - 332) };
  if (preferred === "left")   return { top: clamp(rect.top, 12, vh - 220), left: Math.max(12, rect.left - 332) };
  return { top: clamp(rect.top, 12, vh - 220), left: rect.right + gap };
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(Math.max(v, min), max);
}
