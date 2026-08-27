"use client";
import * as React from "react";
import { Minus, Plus, Maximize2 } from "lucide-react";

const ZOOM_STEPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2] as const;

export interface ZoomControlsProps {
  zoom: number;
  onChange: (next: number) => void;
}

function nearestStep(z: number): number {
  let best = ZOOM_STEPS[0];
  let bestDist = Math.abs(z - best);
  for (const s of ZOOM_STEPS) {
    const d = Math.abs(z - s);
    if (d < bestDist) { best = s; bestDist = d; }
  }
  return best;
}

export function ZoomControls({ zoom, onChange }: ZoomControlsProps) {
  const current = nearestStep(zoom);

  const zoomOut = React.useCallback(() => {
    const i = ZOOM_STEPS.indexOf(current);
    onChange(ZOOM_STEPS[Math.max(0, i - 1)]);
  }, [current, onChange]);

  const zoomIn = React.useCallback(() => {
    const i = ZOOM_STEPS.indexOf(current);
    onChange(ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, i + 1)]);
  }, [current, onChange]);

  const reset = React.useCallback(() => onChange(1), [onChange]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key === "=" || e.key === "+") { e.preventDefault(); zoomIn(); }
      else if (e.key === "-" || e.key === "_") { e.preventDefault(); zoomOut(); }
      else if (e.key === "0") { e.preventDefault(); reset(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomIn, zoomOut, reset]);

  const BTN = "h-7 w-7 grid place-items-center hover:bg-muted text-muted-foreground hover:text-foreground transition-colors";

  return (
    <div
      className="absolute bottom-4 right-4 z-10 flex items-center bg-background border rounded-md shadow-sm overflow-hidden text-xs"
      role="group"
      aria-label="Zoom"
    >
      <button onClick={zoomOut} className={BTN} title="Zoom out (Cmd+−)" aria-label="Zoom out">
        <Minus size={12} />
      </button>
      <button
        onClick={reset}
        className="h-7 px-2 min-w-[3rem] text-center hover:bg-muted transition-colors border-l border-r"
        title="Reset to 100% (Cmd+0)"
        aria-label={`Current zoom ${Math.round(zoom * 100)} percent — click to reset`}
      >
        {Math.round(zoom * 100)}%
      </button>
      <button onClick={zoomIn} className={BTN} title="Zoom in (Cmd+=)" aria-label="Zoom in">
        <Plus size={12} />
      </button>
      <button onClick={reset} className={`${BTN} border-l`} title="Fit (Cmd+0)" aria-label="Fit to screen">
        <Maximize2 size={12} />
      </button>
    </div>
  );
}
