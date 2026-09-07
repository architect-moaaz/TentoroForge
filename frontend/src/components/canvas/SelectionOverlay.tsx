"use client";
import { useEffect, useRef, useState, type CSSProperties, type RefObject, type MouseEvent as ReactMouseEvent } from "react";
import { Copy, Trash2 } from "lucide-react";
import { useEditorStore } from "@/lib/editor-store";
import { AlignmentGuides } from "./AlignmentGuides";
import {
  computeAlignmentGuides,
  pickSnap,
  snapSizeDelta,
  SNAP_TOLERANCE_CANVAS_PX,
  type AlignmentGuide,
  type GuideRect,
} from "./alignment-guides";

/** Structural rect rather than DOMRect: an in-flight resize synthesises the
 *  post-snap box arithmetically (see applyFrame) instead of paying for a second
 *  forced layout, and a synthesised box can't be a DOMRect. */
interface BoxRect { id: string; rect: GuideRect; }

const HANDLE_SIZE = 8; // px
const MIN_SIZE = 16;   // px — don't let a node collapse to nothing

// Each handle records which edges it drags: dx/dy = -1 (left/top edge),
// +1 (right/bottom edge), 0 (this axis unaffected). newSize = start + dir*delta.
function handlePositions(
  rect: GuideRect,
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

/** Ids of a node's siblings — the other children (and slot children) of its
 *  immediate parent. Read from the schema rather than by DOM-querying under the
 *  parent element, because a descendant query would also return grandchildren
 *  and a node would then align to boxes it isn't laid out against. */
function siblingIdsFor(artifacts: any, nodeId: string): string[] {
  for (const page of Object.values(artifacts?.pageSchemas ?? {})) {
    const stack: any[] = [(page as any).root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      const kids: any[] = [
        ...(Array.isArray(n.children) ? n.children : []),
        ...(n.slots ? Object.values(n.slots).flat() : []),
      ];
      if (kids.some((c: any) => c && c.id === nodeId)) {
        return kids
          .filter((c: any) => c && typeof c.id === "string" && c.id !== nodeId)
          .map((c: any) => c.id as string);
      }
      stack.push(...kids);
    }
  }
  return [];
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

/** Live canvas zoom, from CanvasFrame's `transform: scale(zoom)` wrapper.
 *
 * Read as renderedWidth / layoutWidth rather than by parsing the transform or
 * threading the toolbar's zoom prop down here: it is the same rect-over-offset
 * convention startResize already uses to map pointer deltas to intrinsic CSS
 * px, and having exactly one convention in this file is what stops guides from
 * landing in the wrong place at the 50% zoom the editor is routinely driven at.
 */
function canvasZoom(canvas: HTMLElement | null, fallback: number): number {
  const frame = canvas?.closest<HTMLElement>("[data-canvas-frame]") ?? null;
  if (frame && frame.offsetWidth > 0) {
    const z = frame.getBoundingClientRect().width / frame.offsetWidth;
    if (z > 0) return z;
  }
  return fallback > 0 ? fallback : 1;
}

/** Cheap identity for a guide set, so an unchanged set doesn't re-render React
 *  on every animation frame of a drag. */
function guideSignature(gs: AlignmentGuide[]): string {
  return gs
    .map((g) => `${g.axis}${g.movingEdge}${Math.round(g.position)}:${Math.round(g.start)}-${Math.round(g.end)}`)
    .join("|");
}

/**
 * Renders a thin blue outline + 8 Figma-style corner/midpoint handles over all
 * currently-selected nodes, plus the smart alignment guides for an in-flight
 * resize. Sibling to the canvas (NOT a child) so its fixed positioning doesn't
 * interact with the canvas's own layout.
 *
 * Re-measures on:
 *  - selection change
 *  - ResizeObserver fires on any selected element
 *  - scroll/resize of the surrounding viewport
 *
 * All three of those paths are coalesced into a single requestAnimationFrame.
 * Before that, a flick of the scroll wheel delivered several scroll events per
 * frame and each one did N getBoundingClientRect() reads plus a setState — so
 * the overlay both burned layout passes it could never paint and visibly
 * stuttered against the content it was supposed to be glued to.
 *
 * Bounding rects come from getBoundingClientRect() and are passed straight
 * to position:fixed coordinates.
 */
export function SelectionOverlay({
  canvasRef,
}: { canvasRef: RefObject<HTMLElement | null> }) {
  const selectedIds = useEditorStore((s) => s.selectedNodeIds);
  const [boxes, setBoxes] = useState<BoxRect[]>([]);
  const [guides, setGuides] = useState<AlignmentGuide[]>([]);

  /* While a handle drag owns the box, the ResizeObserver/scroll re-measure path
   * must stand down: the drag already knows the new rect (it just wrote the
   * style and read it back), whereas a re-measure scheduled from the observer
   * lands a frame later and would drag the outline one frame behind the
   * content — the exact "handles jump" the overlay is meant to avoid. */
  const draggingRef = useRef(false);
  /* Teardown for an in-flight drag, so unmounting mid-drag (page switch,
   * selection cleared by a keystroke) can't leave window listeners or a stale
   * guide behind. */
  const dragCleanupRef = useRef<(() => void) | null>(null);
  /* Transition the outline only when it is SETTLING — a node resized from the
   * Style panel, a container that reflowed. Never during a pointer drag or a
   * scroll, where a transition makes the overlay lag the thing it is tracking
   * and reads as worse jank than no transition at all. */
  const [smooth, setSmooth] = useState(false);

  useEffect(() => () => { dragCleanupRef.current?.(); }, []);

  // Drag-to-resize from a handle. Only enabled for single selection. Derives the
  // canvas zoom from the element itself (rect.width / offsetWidth) so pixel
  // deltas map to intrinsic CSS px regardless of the canvas transform. Applies a
  // live inline preview during the drag, commits via updateStyle on release.
  //
  // Every pointermove used to write inline styles directly; a mouse reporting at
  // 500Hz therefore produced ~8 style writes per displayed frame, none of which
  // could be seen, and the overlay's own update arrived from a separate
  // ResizeObserver a frame later. The move handler now only records the latest
  // pointer position and asks for an animation frame; applyFrame does exactly
  // one write + one read + one React update per frame, and publishes the
  // overlay box from the same rect in the same frame. onUp FLUSHES a pending
  // frame before committing, so the committed size is still precisely where the
  // pointer was released and not the last frame boundary.
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

    // ---- Alignment references: measured ONCE, here. -------------------------
    // This is the whole performance story for the guides. Resolving a node id to
    // its layout box walks display:contents wrappers and calls
    // getComputedStyle, and each reference box costs a getBoundingClientRect();
    // doing that for every sibling on every pointermove would mean a forced
    // synchronous layout per sibling per event. Instead the references are
    // snapshotted at mousedown and the per-frame work is pure arithmetic over
    // numbers, with exactly one live rect read (the node being resized).
    //
    // The snapshot's known limit: the canvas is normal flow, so growing a node
    // can push later siblings along and their cached rects go stale mid-drag.
    // Accepted deliberately — re-measuring N siblings per frame is the layout
    // thrash this design exists to avoid, and the guides are advisory feedback,
    // not the source of truth for the commit.
    const store0 = useEditorStore.getState();
    const parentEl = (() => {
      const pid = parentIdFor(store0.artifacts, id);
      return pid ? resolveBoxEl(canvasRef.current, pid) : null;
    })();
    const parentRect: GuideRect | null = parentEl ? parentEl.getBoundingClientRect() : null;
    const siblingRects: Array<{ id: string; rect: GuideRect }> = [];
    for (const sid of siblingIdsFor(store0.artifacts, id)) {
      const sel = resolveBoxEl(canvasRef.current, sid);
      if (sel) siblingRects.push({ id: sid, rect: sel.getBoundingClientRect() });
    }
    // Tolerance is authored in canvas px; scale it into the screen px that
    // getBoundingClientRect (and therefore every number in this drag) speaks.
    const zoom = canvasZoom(canvasRef.current, scaleX);
    const tolerance = SNAP_TOLERANCE_CANVAS_PX * zoom;
    const hasReferences = !!parentRect || siblingRects.length > 0;

    let latest: { x: number; y: number; alt: boolean } | null = null;
    let frame = 0;
    let lastSig = "";

    const applyFrame = () => {
      frame = 0;
      const p = latest;
      if (!p) return;

      if (dx !== 0) finalW = Math.max(MIN_SIZE, Math.round(startW + dx * (p.x - startX) / (scaleX || 1)));
      if (dy !== 0) finalH = Math.max(MIN_SIZE, Math.round(startH + dy * (p.y - startY) / (scaleY || 1)));
      if (dx !== 0) el.style.width = `${finalW}px`;
      if (dy !== 0) el.style.height = `${finalH}px`;

      // One forced layout per frame, for both the guides and the overlay box.
      let rect: GuideRect = el.getBoundingClientRect();

      let nextGuides: AlignmentGuide[] = [];
      if (hasReferences) {
        nextGuides = computeAlignmentGuides({
          moving: rect,
          parent: parentRect,
          siblings: siblingRects,
          tolerance,
        });

        // SNAPPING — held Alt suppresses it (the standard convention), so a user
        // who wants 401px next to a 400px sibling is never fought by the guide.
        // Note the snap is stateless: finalW/finalH are recomputed from the raw
        // pointer position every frame and the snap is re-derived, so nothing
        // accumulates and moving out of tolerance releases immediately.
        if (!p.alt) {
          let grewW = 0;
          let grewH = 0;
          if (dx !== 0) {
            const g = pickSnap(nextGuides, "v");
            if (g) {
              grewW = snapSizeDelta(g);
              if (grewW) {
                finalW = Math.max(MIN_SIZE, Math.round(finalW + grewW / (scaleX || 1)));
                el.style.width = `${finalW}px`;
              }
            }
          }
          if (dy !== 0) {
            const g = pickSnap(nextGuides, "h");
            if (g) {
              grewH = snapSizeDelta(g);
              if (grewH) {
                finalH = Math.max(MIN_SIZE, Math.round(finalH + grewH / (scaleY || 1)));
                el.style.height = `${finalH}px`;
              }
            }
          }
          // Synthesise the post-snap box instead of re-reading it: a second
          // getBoundingClientRect() here would force a second layout in the same
          // frame purely to learn a delta we already computed.
          if (grewW || grewH) {
            rect = { left: rect.left, top: rect.top, width: rect.width + grewW, height: rect.height + grewH };
          }
        }
      }

      // Publish the outline + handles from the rect measured in THIS frame, so
      // they move with the content rather than trailing the ResizeObserver.
      setBoxes([{ id, rect }]);

      const sig = guideSignature(nextGuides);
      if (sig !== lastSig) {
        lastSig = sig;
        setGuides(nextGuides);
      }
    };

    const onMove = (ev: MouseEvent) => {
      if (Math.abs(ev.clientX - startX) + Math.abs(ev.clientY - startY) > 2) moved = true;
      latest = { x: ev.clientX, y: ev.clientY, alt: ev.altKey };
      if (!frame) frame = requestAnimationFrame(applyFrame);
    };

    const teardown = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("blur", onUp);
      document.body.style.userSelect = "";
      draggingRef.current = false;
      dragCleanupRef.current = null;
      // Guides are drag-scoped by construction — clearing here is what makes a
      // cancelled, blurred or unmounted drag incapable of stranding one.
      setGuides([]);
    };

    const onUp = () => {
      // Flush a frame that was scheduled but hasn't run: without this the commit
      // would use the size from the last rendered frame rather than the pointer
      // position the user actually released at.
      if (frame) {
        cancelAnimationFrame(frame);
        applyFrame();
      }
      teardown();
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
    draggingRef.current = true;
    dragCleanupRef.current = teardown;
    setSmooth(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    // An alt-tab or a devtools focus steal never delivers mouseup, which used to
    // leave the drag listeners live and (now) would strand a guide on screen.
    window.addEventListener("blur", onUp);
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
    setGuides([]);
    if (!selectedIds.length || !canvasRef.current) {
      setBoxes([]);
      return;
    }

    const measure = () => {
      // The handle drag publishes its own box in-frame; a re-measure here would
      // arrive a frame stale and fight it.
      if (draggingRef.current) return;
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

    // Coalesce every re-measure trigger to one per animation frame. Scroll in
    // particular fires far faster than the compositor paints, and each raw
    // event previously cost N forced layouts + a React render that was thrown
    // away before it could be seen.
    let measureFrame = 0;
    const scheduleMeasure = () => {
      if (measureFrame) return;
      measureFrame = requestAnimationFrame(() => {
        measureFrame = 0;
        measure();
      });
    };
    measure();

    const ros: ResizeObserver[] = [];
    selectedIds.forEach((id) => {
      // Observe the RESOLVED layout box, not the display:contents wrapper span
      // (which generates no box, so its ResizeObserver never fires) — this is
      // what makes the overlay track a library-node resize live.
      const el = resolveBoxEl(canvasRef.current, id);
      if (el) {
        const ro = new ResizeObserver(() => {
          // A size change that is NOT the user dragging (Style panel edit,
          // container reflow, font load) is the one case where easing the
          // outline into its new box looks better than teleporting it.
          if (!draggingRef.current) setSmooth(true);
          scheduleMeasure();
        });
        ro.observe(el);
        ros.push(ro);
      }
    });
    const onViewportChange = () => {
      // Scrolling must never be eased: an outline that lerps toward the content
      // while the content is scrolling is visibly unglued from it.
      setSmooth(false);
      scheduleMeasure();
    };
    window.addEventListener("scroll", onViewportChange, true);
    window.addEventListener("resize", onViewportChange);
    return () => {
      if (measureFrame) cancelAnimationFrame(measureFrame);
      ros.forEach((r) => r.disconnect());
      window.removeEventListener("scroll", onViewportChange, true);
      window.removeEventListener("resize", onViewportChange);
    };
  }, [selectedIds, canvasRef]);

  if (!boxes.length) return null;

  // Applied to the outline + handles only, and only when `smooth` is on — see
  // the state's declaration for why this is off during drags and scrolls.
  // Written inline rather than as a Tailwind arbitrary class so the property
  // list (which contains commas) can't be mangled by class-name parsing.
  const settle: CSSProperties = smooth
    ? { transition: "left 100ms ease-out, top 100ms ease-out, width 100ms ease-out, height 100ms ease-out" }
    : {};

  return (
    <>
      {boxes.map(({ id, rect }, i) => (
        <div key={id}>
          {/* Thin outline */}
          <div
            className="pointer-events-none fixed z-50 border border-blue-500"
            style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height, ...settle }}
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
                  ...settle,
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
      {/* Drawn after the boxes so the hairline sits above the selection outline
          at the same z-index rather than being hidden under it. */}
      <AlignmentGuides guides={guides} />
    </>
  );
}
