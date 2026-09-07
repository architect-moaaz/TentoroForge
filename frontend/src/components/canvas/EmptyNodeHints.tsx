"use client";
import * as React from "react";
import { createPortal } from "react-dom";
import { useEditorStore } from "@/lib/editor-store";
import { hintFor, isVisuallyEmpty, resolveBoxEl, type HintBox } from "./empty-hints";

/**
 * EmptyNodeHints — the label that tells the user what the blank box they just
 * dropped actually is, and what to do with it.
 *
 * The report this answers: "Every thing i open it shows a blank space and how
 * does user know what do do with it… This is not a particular component this is
 * about all component." The automated audit put numbers on it: 14 of 133 palette
 * components render nothing at all with their registry defaults, and every empty
 * Card / Stack / Grid / Form is the same experience — a rectangle with no clue
 * in it.
 *
 * WHY AN OVERLAY, AND NOT DEMO PROPS AT DROP TIME
 * ------------------------------------------------
 * The obvious alternative is to give a dropped node sample content (a Table with
 * sample columns, a Chart with a sample series) in `buildDroppedNode`. That is
 * rejected here on one hard constraint: drop-time props are written into
 * `store.artifacts`, autosave persists `store.artifacts` to
 * `src/schemas/<page>.json`, and the generator builds the app from those files.
 * Sample rows would therefore SHIP into the user's application unless they
 * remembered to delete every one — the failure mode being a production inventory
 * screen listing "Sample Product A". "Deleted by default" is not a guarantee.
 *
 * This overlay cannot ship, structurally rather than by intent: it lives in the
 * editor frontend, it never touches the store, and no package the scaffold or the
 * generator builds imports it — the same argument GridGuides makes for the cell
 * outlines it draws, and the same reason those are not painted by GridCell.
 *
 * Unlike AlignmentGuides / DropIndicator / GridGuides — which are transient and
 * position:fixed in viewport space — these are STANDING annotations, so they are
 * portalled into the scrolling canvas and positioned in its coordinate space.
 * That keeps them off the surrounding editor chrome and lets them scroll with
 * the content instead of being re-measured against it. pointer-events-none so
 * a hint can never eat the click or the drop it exists to invite. Amber, sitting
 * below the blue of selection and the green of the drop indicator — it is a
 * standing annotation, not a transient one, so it must not compete with either.
 */

export function EmptyNodeHints({
  canvasRef,
}: {
  canvasRef: React.RefObject<HTMLElement | null>;
}) {
  const [boxes, setBoxes] = React.useState<HintBox[]>([]);
  // The scrolling canvas element the hints are portalled into. Held in state
  // rather than read during render so the first paint after mount still finds it.
  const [portalHost, setPortalHost] = React.useState<HTMLElement | null>(null);
  // Any dispatch replaces the artifacts object — the cheap "the tree changed"
  // signal, exactly as GridGuides uses it. A node that has just been given
  // content stops being empty on the next measure.
  const artifacts = useEditorStore((s) => s.artifacts);

  React.useEffect(() => {
    const host = canvasRef.current;
    if (!host) {
      setBoxes([]);
      return;
    }

    /** id → node, over every page in the store (cheap; trees are small). */
    const index = new Map<string, { type: string; props?: Record<string, unknown> }>();
    for (const page of Object.values(
      (artifacts as any)?.pageSchemas ?? {},
    ) as any[]) {
      const stack: any[] = [page?.root];
      while (stack.length) {
        const n = stack.pop();
        if (!n) continue;
        if (n.id) index.set(n.id, { type: n.type, props: n.props });
        if (Array.isArray(n.children)) stack.push(...n.children);
        if (n.slots && typeof n.slots === "object") {
          for (const arr of Object.values(n.slots) as any[]) {
            if (Array.isArray(arr)) stack.push(...arr);
          }
        }
      }
    }

    const measure = () => {
      const next: HintBox[] = [];
      // THE CANVAS ROOT, NOT AN ANCESTOR SCROLLER.
      //
      // Portalling into `main` looked right — `main` is what scrolls — but the
      // canvas sits inside NESTED scrollers, so a hint positioned in `main`'s
      // space stayed put while the content moved in an inner one, and every hint
      // drifted off the box it labels. Reported as "everything jiggles when I
      // scroll"; it is really a constant offset that only shows up once you move.
      //
      // The canvas root is already `position: relative` and IS the content, so a
      // hint placed inside it is carried by whatever scrolls, with no offset to
      // recompute and nothing to keep in sync.
      setPortalHost((prev) => (prev === host ? prev : host));
      host.querySelectorAll<HTMLElement>("[data-node-id]").forEach((el) => {
        const nodeId = el.getAttribute("data-node-id");
        if (!nodeId) return;
        const node = index.get(nodeId);
        if (!node) return;
        const box = resolveBoxEl(el);
        // No box at all is the zero-DOM class (Repeat / Conditional /
        // DataBoundary / Slot). There is nothing on screen to annotate, so
        // they are out of this overlay's reach by construction — see the
        // report; fixing those needs the renderer, not the editor.
        if (!box || !isVisuallyEmpty(box)) return;
        const label = hintFor(node.type, node.props);
        if (!label) return;
        const rect = box.getBoundingClientRect();
        // A box with no area cannot be annotated legibly and, more to the
        // point, the user cannot see it either.
        if (rect.width < 24 || rect.height < 12) return;
        // OFFSET FROM THE CANVAS ROOT — and NO scroll term.
        //
        // The hint and the node it labels are now inside the same scrolled
        // content, so the distance between them never changes and there is
        // nothing to keep in sync. Adding a scroll offset here (as this did when
        // it portalled into `main`) double-counted the scroll the browser was
        // already applying.
        //
        // No explicit clip either: an ancestor of the canvas root is
        // `overflow: hidden`, so anything reaching past the page is clipped for
        // free, correctly at every scroll position.
        const hostRect = host.getBoundingClientRect();
        next.push({
          key: nodeId,
          nodeId,
          type: node.type,
          label,
          left: rect.left - hostRect.left,
          top: rect.top - hostRect.top,
          width: rect.width,
          height: rect.height,
        });
      });
      setBoxes(next);
    };

    // One measure per frame. Each pass reads getBoundingClientRect() for every
    // empty node, which forces layout; scroll fires far faster than the
    // compositor paints. Same batching as GridGuides and SelectionOverlay.
    let frame = 0;
    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        measure();
      });
    };
    // The first paint after a drop has not laid out yet when this effect runs,
    // so measure on the next frame as well as now.
    measure();
    schedule();

    // NO SCROLL LISTENER — that is what made the whole canvas jiggle.
    //
    // These hints are absolutely positioned INSIDE the scrolling container, in
    // its coordinate space, so the browser already moves them with the content
    // at no cost and they cannot drift. Re-measuring on scroll actively broke
    // that: each pass recomputes `rect.top - hostRect.top + scrollTop`, and
    // during a scroll the rect and the scroll offset are read a frame apart, so
    // the two no longer cancel and every hint twitches against the content it
    // is labelling. (The listener is a leftover from when these were
    // position:fixed in viewport space, where re-measuring WAS required.)
    //
    // ResizeObserver still fires when the layout actually changes size, which
    // is the only time a stored position becomes wrong.
    const ro = new ResizeObserver(schedule);
    ro.observe(host);
    window.addEventListener("resize", schedule);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      ro.disconnect();
      window.removeEventListener("resize", schedule);
    };
  }, [canvasRef, artifacts]);

  if (!boxes.length || !portalHost) return null;
  // PORTALLED INTO THE CANVAS, NOT position:fixed ON THE BODY.
  // A positioned element paints above the Properties panel's static content no
  // matter how low its z-index goes, and the panel OVERLAYS the canvas rather
  // than shrinking it (canvas viewport 268..1525, panel ~1270..1568), so no
  // amount of clipping in viewport coordinates can separate the two. Hints were
  // drawn across the toolbar's Export button and over the DENSITY / ELEVATION
  // controls. Rendering inside the scroll container instead means that element's
  // own `overflow` clips them, and the panel stacks above them the ordinary way.
  //
  // `b.left` / `b.top` are ALREADY in this container's coordinate space — see
  // the measure pass. Converting again here would re-apply the scroll offset.
  return createPortal(
    <>
      {boxes.map((b) => (
        <div
          key={b.key}
          data-empty-hint={b.type}
          className="pointer-events-none absolute z-20 flex items-center justify-center overflow-hidden rounded-[3px] px-2"
          style={{
            left: b.left,
            top: b.top,
            width: b.width,
            height: b.height,
            // Inline rather than Tailwind classes for the same reason
            // GridGuides does it: globals.css applies a base border-colour
            // reset to `*`, which silently repaints utility borders.
            border: "1px dashed rgba(217, 119, 6, 0.55)",
            background: "rgba(217, 119, 6, 0.06)",
          }}
        >
          <span
            className="max-w-full truncate text-center text-[11px] font-medium leading-tight"
            style={{ color: "rgba(146, 64, 14, 0.9)" }}
          >
            {b.label}
          </span>
        </div>
      ))}
    </>,
    portalHost,
  );
}
