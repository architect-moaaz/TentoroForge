"use client";

/**
 * One screen of the board, drawn in the company's brand, in a phone or a
 * desktop frame. The picture when a browser took one; else the document
 * itself, live, in a frame that may run nothing (`sandbox` with no
 * allowances) scaled to fit. Drawing and failed states sit over the frame.
 */
import { Loader2, RefreshCw, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AuthImage, useFileText } from "./AuthImage";
import type { Drawing } from "./types";

export const VIEWPORTS: Record<Drawing["viewport"], { w: number; h: number }> = {
  phone: { w: 390, h: 844 },
  desktop: { w: 1280, h: 800 },
};

export function DrawingFrame({ drawing, path, width, live = false }:
  { drawing: Drawing; path: (id: string, kind: "html" | "png") => string; width: number; live?: boolean }) {
  const vp = VIEWPORTS[drawing.viewport] ?? VIEWPORTS.desktop;
  const scale = width / vp.w;
  const height = Math.round(vp.h * scale);
  // The document is fetched only when it is what will be shown.
  const html = useFileText(drawing.html && (live || !drawing.png) ? path(drawing.id, "html") : null);
  if (!live && drawing.png) {
    return (
      <AuthImage path={path(drawing.id, "png")} alt={drawing.caption || drawing.screen}
        className="w-full object-cover object-top" />
    );
  }
  return (
    <div style={{ width, height }} className="overflow-hidden bg-white">
      {html === null ? (
        <div className="h-full w-full animate-pulse bg-muted" />
      ) : (
        <iframe
          title={drawing.screen}
          sandbox=""
          srcDoc={html}
          style={{ width: vp.w, height: vp.h, transform: `scale(${scale})`, transformOrigin: "top left", border: 0 }}
        />
      )}
    </div>
  );
}

export function ScreenDrawing({ drawing, path, onOpen, onRedraw, stale = false }:
  { drawing: Drawing | undefined; path: (id: string, kind: "html" | "png") => string;
    onOpen: (d: Drawing) => void; onRedraw: () => void; stale?: boolean }) {
  const viewport = drawing?.viewport ?? "desktop";
  const phone = viewport === "phone";
  const width = phone ? 180 : 320;
  const vp = VIEWPORTS[viewport];
  const height = Math.round(vp.h * (width / vp.w));
  const done = drawing?.status === "done";
  return (
    <div className="relative mx-auto" style={{ width }}>
      <div
        className={`overflow-hidden border bg-white shadow-sm ${phone ? "rounded-[22px] border-[6px] border-zinc-800" : "rounded-md"} ${done ? "cursor-zoom-in" : ""}`}
        style={{ height }}
        onClick={() => { if (drawing && done) onOpen(drawing); }}
        data-testid="drawing-frame"
      >
        {drawing && done && <DrawingFrame drawing={drawing} path={path} width={width - (phone ? 12 : 2)} />}
        {(!drawing || drawing.status === "drawing") && (
          <div className="h-full w-full flex flex-col items-center justify-center gap-2 text-xs text-muted-foreground bg-muted/40"
            data-testid="drawing-status">
            {drawing ? <><Loader2 className="h-4 w-4 animate-spin" /> Drawing…</> : <span>Not drawn yet</span>}
          </div>
        )}
        {drawing?.status === "failed" && (
          <div className="h-full w-full flex flex-col items-center justify-center gap-2 p-3 text-center text-xs text-destructive bg-muted/40"
            data-testid="drawing-status">
            <AlertTriangle className="h-4 w-4" />
            <span>Could not be drawn{drawing.error ? `: ${drawing.error}` : ""}</span>
          </div>
        )}
      </div>
      {(stale || drawing?.status === "failed" || !drawing) && (
        <Button size="sm" variant="outline" className="absolute right-1 top-1 h-7 px-2 text-xs bg-background/90"
          onClick={(e) => { e.stopPropagation(); onRedraw(); }} title={stale ? "The screen changed since it was drawn" : undefined}>
          <RefreshCw className="h-3 w-3 mr-1" /> {drawing ? "Redraw" : "Draw"}
        </Button>
      )}
    </div>
  );
}
