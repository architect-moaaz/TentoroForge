"use client";
import * as React from "react";

export function DropIndicator({
  hoverParent,
  canvasRef,
}: {
  hoverParent: string | null;
  canvasRef: React.RefObject<HTMLElement | null>;
}) {
  const [rect, setRect] = React.useState<DOMRect | null>(null);

  React.useEffect(() => {
    if (!hoverParent || !canvasRef.current) {
      setRect(null);
      return;
    }
    let el: HTMLElement | null = canvasRef.current.querySelector(
      `[data-node-id="${hoverParent}"]`,
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
    if (el) setRect(el.getBoundingClientRect());
  }, [hoverParent, canvasRef]);

  if (!rect) return null;
  return (
    <div
      className="pointer-events-none fixed z-40 bg-green-400/15 border-2 border-dashed border-green-500"
      style={{
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
      }}
      data-tentoro-drop-indicator=""
    />
  );
}
