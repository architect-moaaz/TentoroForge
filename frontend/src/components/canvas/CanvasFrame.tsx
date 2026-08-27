"use client";
import { ReactNode } from "react";

const DEVICE_WIDTH = { mobile: 375, tablet: 768, desktop: 1280 } as const;

export interface CanvasFrameProps {
  device: "mobile" | "tablet" | "desktop";
  /** 1 = 100%. Range enforced by the toolbar (0.25–2.0). */
  zoom?: number;
  children: ReactNode;
}

export function CanvasFrame({ device, zoom = 1, children }: CanvasFrameProps) {
  const w = DEVICE_WIDTH[device];
  // Reserve scaled width so the surrounding scroll container reflects the
  // visible size of the device frame — without this, the canvas overflows
  // (zoom > 1) or leaves a giant empty gap (zoom < 1).
  const scaledW = w * zoom;
  const scaledMinH = 600 * zoom;
  return (
    <div className="bg-slate-50 dark:bg-slate-900 min-h-full p-4 overflow-auto">
      <div
        className="mx-auto"
        style={{ width: scaledW, minHeight: scaledMinH }}
      >
        <div
          className="bg-background shadow-sm border rounded overflow-hidden origin-top-left"
          style={{
            width: w,
            minHeight: 600,
            transform: `scale(${zoom})`,
          }}
          data-canvas-frame=""
        >
          {children}
        </div>
      </div>
    </div>
  );
}
