"use client";
import { useEffect, useState, type RefObject, type MouseEvent as ReactMouseEvent } from "react";
import { Copy, Trash2 } from "lucide-react";
import { useEditorStore } from "@/lib/editor-store";

interface BoxRect { id: string; rect: DOMRect; }

const HANDLE_SIZE = 8; // px
const MIN_SIZE = 16;   // px — don't let a node collapse to nothing

// Each handle records which edges it drags: dx/dy = -1 (left/top edge),
// +1 (right/bottom edge), 0 (this axis unaffected). newSize = start + dir*delta.
function handlePositions(
  rect: DOMRect,
): Array<{ left: number; top: number; cursor: string; dx: -1 | 0 | 1; dy: -1 | 0 | 1 }> {
  const { left, top, width, height } = rect;
  const right = left + width;
  const bottom = top + height;
  const cx = left + width / 2;
  const cy = top + height / 2;
  const half = HANDLE_SIZE / 2;
  return [
    { left: left - half,  top: top - half,    cursor: "nwse-resize", dx: -1, dy: -1 }, // top-left
    { left: cx - half,    top: top - half,    cursor: "ns-resize",   dx:  0, dy: -1 }, // top-mid
    { left: right - half, top: top - half,    cursor: "nesw-resize", dx:  1, dy: -1 }, // top-right
    { left: right - half, top: cy - half,     cursor: "ew-resize",   dx:  1, dy:  0 }, // right-mid
    { left: right - half, top: bottom - half, cursor: "nwse-resize", dx:  1, dy:  1 }, // bottom-right
    { left: cx - half,    top: bottom - half, cursor: "ns-resize",   dx:  0, dy:  1 }, // bottom-mid
    { left: left - half,  top: bottom - half, cursor: "nesw-resize", dx: -1, dy:  1 }, // bottom-left
    { left: left - half,  top: cy - half,     cursor: "ew-resize",   dx: -1, dy:  0 }, // left-mid
  ];
}

/** Resolve the layout-bearing element for a node id, walking through any
 * `display:contents` wrapper the library dispatcher adds around a component. */
function resolveBoxEl(
  canvas: HTMLElement | null,
  id: string,
): HTMLElement | null {
  let el = canvas?.querySelector<HTMLElement>(`[data-node-id="${id}"]`) ?? null;
  if (el && getComputedStyle(el).display === "contents") {
    const walk = (e: HTMLElement): HTMLElement | null => {
      for (const child of Array.from(e.children) as HTMLElement[]) {
        if (getComputedStyle(child).display !== "contents") return child;
        const inner = walk(child);
        if (inner) return inner;
      }
      return null;
    };
    el = walk(el);
  }
  return el;
}

/** Find the immediate parent id of a node (searches children + slots). */
function parentIdFor(artifacts: any, nodeId: string): string | null {
  for (const page of Object.values(artifacts?.pageSchemas ?? {})) {
    const stack: any[] = [(page as any).root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      const kids: any[] = [
        ...(Array.isArray(n.children) ? n.children : []),
        ...(n.slots ? Object.values(n.slots).flat() : []),
      ];
      if (kids.some((c: any) => c && c.id === nodeId)) return n.id;
      stack.push(...kids);
    }
  }
  return null;
}

/** Find which page a node id lives on (children + slots). */
function pageIdFor(artifacts: any, nodeId: string): string | null {
  for (const [pid, page] of Object.entries(artifacts?.pageSchemas ?? {})) {
    const stack: any[] = [(page as any).root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      if (n.id === nodeId) return pid;
      if (Array.isArray(n.children)) stack.push(...n.children);
      if (n.slots) for (const arr of Object.values(n.slots) as any[]) if (Array.isArray(arr)) stack.push(...arr);
    }
  }
  return null;
}

/**
 * Renders a thin blue outline + 8 Figma-style corner/midpoint handles over all
 * currently-selected nodes. Sibling to the canvas (NOT a child) so its fixed
 * positioning doesn't interact with the canvas's own layout.
 *
 * Re-measures on:
 *  - selection change
 *  - ResizeObserver fires on any selected element
 *  - scroll/resize of the surrounding viewport
 *
 * Bounding rects come from getBoundingClientRect() and are passed straight
 * to position:fixed coordinates.
 */
export function SelectionOverlay({
  canvasRef,
}: { canvasRef: RefObject<HTMLElement | null> }) {
  const selectedIds = useEditorStore((s) => s.selectedNodeIds);
  const [boxes, setBoxes] = useState<BoxRect[]>([]);

  // Drag-to-resize from a handle. Only enabled for single selection. Derives the
  // canvas zoom from the element itself (rect.width / offsetWidth) so pixel
  // deltas map to intrinsic CSS px regardless of the canvas transform. Applies a
  // live inline preview during the drag, commits via updateStyle on release.
  const startResize = (
    e: ReactMouseEvent,
    id: string,
    dx: -1 | 0 | 1,
    dy: -1 | 0 | 1,
  ) => {
    e.preventDefault();
    e.stopPropagation();
    const el = resolveBoxEl(canvasRef.current, id);
    if (!el) return;
    const startX = e.clientX;
    const startY = e.clientY;
    const startW = el.offsetWidth;
    const startH = el.offsetHeight;
    const r = el.getBoundingClientRect();
    const scaleX = startW > 0 ? r.width / startW : 1;
    const scaleY = startH > 0 ? r.height / startH : 1;
    let moved = false;
    let finalW = startW;
    let finalH = startH;

    const onMove = (ev: MouseEvent) => {
      if (Math.abs(ev.clientX - startX) + Math.abs(ev.clientY - startY) > 2) moved = true;
      if (dx !== 0) {
        finalW = Math.max(MIN_SIZE, Math.round(startW + dx * (ev.clientX - startX) / (scaleX || 1)));
        el.style.width = `${finalW}px`;
      }
      if (dy !== 0) {
        finalH = Math.max(MIN_SIZE, Math.round(startH + dy * (ev.clientY - startY) / (scaleY || 1)));
        el.style.height = `${finalH}px`;
      }
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.style.userSelect = "";
      if (!moved) return;
      const store = useEditorStore.getState();
      const pageId = pageIdFor(store.artifacts, id);
      if (!pageId) return;
      // Coalesce width+height of one corner drag into a single undo step.
      const actions: Array<Parameters<typeof store.dispatch>[0]> = [];
      if (dx !== 0) actions.push({ type: "updateStyle", pageId, nodeId: id, styleKey: "width", value: `${finalW}px` });
      if (dy !== 0) actions.push({ type: "updateStyle", pageId, nodeId: id, styleKey: "height", value: `${finalH}px` });
      if (actions.length === 1) store.dispatch(actions[0]);
      else if (actions.length > 1) store.dispatchBatch(actions);
    };
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  // On-canvas remove / duplicate (the previous affordance was keyboard-only, and
  // Delete is ignored while focus is in an input). Both go through the same
  // reducer actions the keymap uses, so undo/redo behave identically.
  const isRootNode = (id: string): boolean => {
    const arts: any = useEditorStore.getState().artifacts;
    return Object.values(arts?.pageSchemas ?? {}).some((p: any) => p?.root?.id === id);
  };
  const removeNode = (id: string) => {
    const store = useEditorStore.getState();
    const pageId = pageIdFor(store.artifacts, id);
    if (!pageId) return;
    const parentId = parentIdFor(store.artifacts, id);
    store.dispatch({ type: "removeNode", pageId, nodeId: id });
    // Stay oriented: select the parent (unless it's the page root) rather than
    // clearing selection to nothing.
    if (parentId && !isRootNode(parentId)) store.setSelection(parentId);
    else store.clearSelection();
  };
  const duplicateNode = (id: string) => {
    const store = useEditorStore.getState();
    const pageId = pageIdFor(store.artifacts, id);
    if (!pageId) return;
    store.dispatch({ type: "duplicateNode", pageId, nodeId: id });
  };

  useEffect(() => {
    if (!selectedIds.length || !canvasRef.current) {
      setBoxes([]);
      return;
    }

    const measure = () => {
      const out: BoxRect[] = [];
      for (const id of selectedIds) {
        const el = resolveBoxEl(canvasRef.current, id);
        // Push even a 0x0 box (empty container) so its outline/label/action-bar
        // still render — otherwise a dropped empty Stack/Row/Grid is invisible
        // AND permanently unclickable on the canvas.
        if (el) out.push({ id, rect: el.getBoundingClientRect() });
      }
      setBoxes(out);
    };
    measure();

    const ros: ResizeObserver[] = [];
    selectedIds.forEach((id) => {
      // Observe the RESOLVED layout box, not the display:contents wrapper span
      // (which generates no box, so its ResizeObserver never fires) — this is
      // what makes the overlay track a library-node resize live.
      const el = resolveBoxEl(canvasRef.current, id);
      if (el) {
        const ro = new ResizeObserver(measure);
        ro.observe(el);
        ros.push(ro);
      }
    });
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      ros.forEach((r) => r.disconnect());
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [selectedIds, canvasRef]);

  if (!boxes.length) return null;

  return (
    <>
      {boxes.map(({ id, rect }, i) => (
        <div key={id}>
          {/* Thin outline */}
          <div
            className="pointer-events-none fixed z-50 border border-blue-500"
            style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
            data-tentoro-selection-overlay=""
          />
          {/* 8 corner/midpoint handles. Interactive (drag-to-resize) only for a
              single selection; decorative for multi-select. */}
          {handlePositions(rect).map((pos, j) => {
            const resizable = boxes.length === 1;
            return (
              <div
                key={j}
                onMouseDown={resizable ? (e) => startResize(e, id, pos.dx, pos.dy) : undefined}
                className={`fixed z-50 bg-background border border-blue-500 ${resizable ? "pointer-events-auto" : "pointer-events-none"}`}
                style={{
                  left: pos.left,
                  top: pos.top,
                  width: HANDLE_SIZE,
                  height: HANDLE_SIZE,
                  cursor: pos.cursor,
                }}
              />
            );
          })}
          {/* Label badge (only for first selection or single selection) */}
          {(boxes.length === 1 || i === 0) && (
            <div
              className="pointer-events-none fixed z-50 bg-blue-500 text-white text-[10px] px-1.5 py-0.5 rounded-sm font-mono"
              style={{ left: rect.left, top: Math.max(0, rect.top - 18) }}
            >
              {boxes.length === 1 ? id : `${id} +${boxes.length - 1}`}
            </div>
          )}

          {/* Action bar — duplicate / delete, single non-root selection only.
              Root can be neither duplicated nor removed (the reducer rejects it),
              so the bar is hidden there rather than showing a no-op. */}
          {boxes.length === 1 && !isRootNode(id) && (
            <div
              className="pointer-events-auto fixed z-50 flex items-center gap-px rounded-md border border-blue-500 bg-background shadow-sm overflow-hidden"
              style={{ left: Math.max(0, rect.left + rect.width - 46), top: Math.max(0, rect.top - 24) }}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                title="Duplicate (⌘D)"
                aria-label="Duplicate component"
                className="flex h-5 w-5 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground"
                onClick={() => duplicateNode(id)}
              >
                <Copy size={11} />
              </button>
              <button
                type="button"
                title="Delete (⌫)"
                aria-label="Delete component"
                className="flex h-5 w-5 items-center justify-center text-muted-foreground hover:bg-red-500 hover:text-white"
                onClick={() => removeNode(id)}
              >
                <Trash2 size={11} />
              </button>
            </div>
          )}
        </div>
      ))}
    </>
  );
}
