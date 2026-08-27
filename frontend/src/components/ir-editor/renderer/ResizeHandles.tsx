"use client";

import { useCallback, useRef } from "react";
import type { NodePath } from "./types";
import { useIREditorStore } from "@/stores/ir-editor";

type Edge = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

const CURSORS: Record<Edge, string> = {
  n: "cursor-n-resize",
  s: "cursor-s-resize",
  e: "cursor-e-resize",
  w: "cursor-w-resize",
  ne: "cursor-ne-resize",
  nw: "cursor-nw-resize",
  se: "cursor-se-resize",
  sw: "cursor-sw-resize",
};

interface ResizeHandlesProps {
  path: NodePath;
  /** Current width of the element (from getBoundingClientRect) */
  containerRef: React.RefObject<HTMLDivElement | null>;
}

export function ResizeHandles({ path, containerRef }: ResizeHandlesProps) {
  const dragState = useRef<{
    edge: Edge;
    startX: number;
    startY: number;
    startWidth: number;
    startHeight: number;
  } | null>(null);

  const handlePointerDown = useCallback(
    (edge: Edge) => (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();

      const el = containerRef.current;
      if (!el) return;

      const rect = el.getBoundingClientRect();
      dragState.current = {
        edge,
        startX: e.clientX,
        startY: e.clientY,
        startWidth: rect.width,
        startHeight: rect.height,
      };

      const handlePointerMove = (me: PointerEvent) => {
        if (!dragState.current) return;
        const { edge: e2, startX, startY, startWidth, startHeight } = dragState.current;
        const dx = me.clientX - startX;
        const dy = me.clientY - startY;

        let newWidth = startWidth;
        let newHeight = startHeight;

        if (e2.includes("e")) newWidth = Math.max(40, startWidth + dx);
        if (e2.includes("w")) newWidth = Math.max(40, startWidth - dx);
        if (e2.includes("s")) newHeight = Math.max(24, startHeight + dy);
        if (e2.includes("n")) newHeight = Math.max(24, startHeight - dy);

        // Apply live preview via inline style
        const target = containerRef.current;
        if (target) {
          if (e2.includes("e") || e2.includes("w")) {
            target.style.width = `${Math.round(newWidth)}px`;
          }
          if (e2.includes("s") || e2.includes("n")) {
            target.style.height = `${Math.round(newHeight)}px`;
          }
        }
      };

      const handlePointerUp = (ue: PointerEvent) => {
        document.removeEventListener("pointermove", handlePointerMove);
        document.removeEventListener("pointerup", handlePointerUp);

        if (!dragState.current) return;
        const { edge: e2, startX, startY, startWidth, startHeight } = dragState.current;
        const dx = ue.clientX - startX;
        const dy = ue.clientY - startY;
        dragState.current = null;

        // Skip tiny drags (< 3px)
        if (Math.abs(dx) < 3 && Math.abs(dy) < 3) {
          // Reset inline styles
          const target = containerRef.current;
          if (target) {
            target.style.width = "";
            target.style.height = "";
          }
          return;
        }

        let newWidth = startWidth;
        let newHeight = startHeight;
        if (e2.includes("e")) newWidth = Math.max(40, startWidth + dx);
        if (e2.includes("w")) newWidth = Math.max(40, startWidth - dx);
        if (e2.includes("s")) newHeight = Math.max(24, startHeight + dy);
        if (e2.includes("n")) newHeight = Math.max(24, startHeight - dy);

        const ops: Array<{ type: "setProp"; path: NodePath; prop: string; value: unknown }> = [];

        if (e2.includes("e") || e2.includes("w")) {
          ops.push({ type: "setProp", path, prop: "width", value: `${Math.round(newWidth)}px` });
        }
        if (e2.includes("s") || e2.includes("n")) {
          ops.push({ type: "setProp", path, prop: "height", value: `${Math.round(newHeight)}px` });
        }

        if (ops.length > 0) {
          useIREditorStore.getState().applyOps(ops);
        }

        // Reset inline styles (IR re-render will apply the new size)
        const target = containerRef.current;
        if (target) {
          target.style.width = "";
          target.style.height = "";
        }
      };

      document.addEventListener("pointermove", handlePointerMove);
      document.addEventListener("pointerup", handlePointerUp);
    },
    [path, containerRef],
  );

  // Edge handles (lines along edges)
  const edgeHandles: { edge: Edge; className: string }[] = [
    { edge: "e", className: "absolute top-0 -right-1 w-2 h-full" },
    { edge: "w", className: "absolute top-0 -left-1 w-2 h-full" },
    { edge: "s", className: "absolute -bottom-1 left-0 h-2 w-full" },
    { edge: "n", className: "absolute -top-1 left-0 h-2 w-full" },
  ];

  // Corner handles (small squares at corners)
  const cornerHandles: { edge: Edge; className: string }[] = [
    { edge: "se", className: "absolute -bottom-1.5 -right-1.5 w-3 h-3 bg-blue-500 rounded-sm border border-white" },
    { edge: "sw", className: "absolute -bottom-1.5 -left-1.5 w-3 h-3 bg-blue-500 rounded-sm border border-white" },
    { edge: "ne", className: "absolute -top-1.5 -right-1.5 w-3 h-3 bg-blue-500 rounded-sm border border-white" },
    { edge: "nw", className: "absolute -top-1.5 -left-1.5 w-3 h-3 bg-blue-500 rounded-sm border border-white" },
  ];

  return (
    <>
      {/* Edge resize zones (invisible, just for cursor + drag) */}
      {edgeHandles.map(({ edge, className }) => (
        <div
          key={edge}
          className={`${className} ${CURSORS[edge]} z-50`}
          onPointerDown={handlePointerDown(edge)}
        />
      ))}
      {/* Corner handles (visible blue squares) */}
      {cornerHandles.map(({ edge, className }) => (
        <div
          key={edge}
          className={`${className} ${CURSORS[edge]} z-50`}
          onPointerDown={handlePointerDown(edge)}
        />
      ))}
    </>
  );
}
