"use client";
import * as React from "react";
import { resolveNodeBox } from "./layout-box";

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
    const el = resolveNodeBox(canvasRef.current, hoverParent);
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
