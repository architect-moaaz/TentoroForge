import { useEffect, useRef, useState } from "react";

export type ResizeHandle = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

export interface ResizeDragOptions {
  onDelta: (dx: number, dy: number, handle: ResizeHandle) => void;
  onCommit: (dx: number, dy: number, handle: ResizeHandle) => void;
}

export function useResizeDrag(opts: ResizeDragOptions) {
  const start = useRef<{ x: number; y: number; handle: ResizeHandle } | null>(null);
  const [active, setActive] = useState<ResizeHandle | null>(null);
  // Keep a stable reference to opts so the effect doesn't re-subscribe on every render
  const optsRef = useRef(opts);
  optsRef.current = opts;

  function startDrag(handle: ResizeHandle, e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    start.current = { x: e.clientX, y: e.clientY, handle };
    setActive(handle);
  }

  useEffect(() => {
    if (!active) return;

    function onMove(e: MouseEvent) {
      if (!start.current) return;
      optsRef.current.onDelta(
        e.clientX - start.current.x,
        e.clientY - start.current.y,
        start.current.handle
      );
    }

    function onUp(e: MouseEvent) {
      if (!start.current) return;
      optsRef.current.onCommit(
        e.clientX - start.current.x,
        e.clientY - start.current.y,
        start.current.handle
      );
      start.current = null;
      setActive(null);
    }

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [active]);

  return { active, startDrag };
}
