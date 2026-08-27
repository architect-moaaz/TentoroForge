"use client";
import * as React from "react";
import type { ReorderIndicatorState } from "./hooks/useReorder";

/**
 * Visual feedback for a drag-to-reorder in progress:
 *  - "inside"  → a green fill over the hovered container (drop as its child)
 *  - "before"/"after" → a thick green line at the top/bottom edge of the
 *    hovered node (drop as a sibling on that side)
 *
 * Measures the target via getBoundingClientRect() into position:fixed coords,
 * matching SelectionOverlay / DropIndicator. Purely presentational —
 * pointer-events-none so it never intercepts the drag.
 */
export function ReorderIndicator({
  indicator,
  canvasRef,
}: {
  indicator: ReorderIndicatorState | null;
  canvasRef: React.RefObject<HTMLElement | null>;
}) {
  const [rect, setRect] = React.useState<DOMRect | null>(null);

  React.useEffect(() => {
    if (!indicator || !canvasRef.current) {
      setRect(null);
      return;
    }
    let el: HTMLElement | null = canvasRef.current.querySelector(
      `[data-node-id="${indicator.targetId}"]`,
    );
    if (el && getComputedStyle(el).display === "contents") {
      const walker = (e: HTMLElement): HTMLElement | null => {
        for (const child of Array.from(e.children) as HTMLElement[]) {
          if (getComputedStyle(child).display !== "contents") return child;
          const inner = walker(child);
          if (inner) return inner;
        }
        return null;
      };
      el = walker(el);
    }
    setRect(el ? el.getBoundingClientRect() : null);
  }, [indicator, canvasRef]);

  if (!indicator || !rect) return null;

  if (indicator.pos === "inside") {
    return (
      <div
        className="pointer-events-none fixed z-40 bg-green-400/15 border-2 border-green-500 rounded-sm"
        style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
        data-tentoro-reorder-indicator="inside"
      />
    );
  }

  const top = indicator.pos === "before" ? rect.top - 1 : rect.bottom - 1;
  return (
    <div
      className="pointer-events-none fixed z-50"
      style={{ left: rect.left, top, width: rect.width, height: 3 }}
      data-tentoro-reorder-indicator={indicator.pos}
    >
      <div className="h-[3px] w-full bg-green-500 rounded-full" />
    </div>
  );
}
