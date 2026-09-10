"use client";
import { useEditorStore } from "@/lib/editor-store";

/** The node under a pointer/mouse event, or null over bare canvas. */
function nodeIdAt(target: EventTarget | null): string | null {
  const el = (target as HTMLElement | null)?.closest?.("[data-node-id]") as
    | HTMLElement
    | null;
  return el?.getAttribute("data-node-id") ?? null;
}

/**
 * Apply the selection this event asks for.
 *   - plain      → setSelection (replace, single)
 *   - shift      → extendSelection (append without dup)
 *   - cmd/ctrl   → toggleSelection (add or remove)
 *   - bare canvas → clearSelection
 */
function applySelection(
  id: string | null,
  mods: { shiftKey: boolean; metaKey: boolean; ctrlKey: boolean },
): void {
  const s = useEditorStore.getState();
  if (!id) {
    s.clearSelection();
    return;
  }
  if (mods.shiftKey) s.extendSelection(id);
  else if (mods.metaKey || mods.ctrlKey) s.toggleSelection(id);
  else s.setSelection(id);
}

/**
 * Returns a click handler to mount on the canvas wrapper. On any click,
 * walks up from the target to the nearest [data-node-id] and selects it.
 *
 * Stops propagation so the underlying rendered component's own onClick
 * (e.g. real button submitForm) doesn't fire while the user is editing.
 */
export function useCanvasClick() {
  return (e: React.MouseEvent) => {
    const id = nodeIdAt(e.target);
    if (!id) {
      applySelection(null, e);
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    applySelection(id, e);
  };
}

/**
 * SELECT ON POINTER-DOWN, IN THE CAPTURE PHASE — the design-time convention.
 *
 * Reported against DropdownMenu: "the node cannot be selected in the editor, so
 * its Props panel is unreachable… click the trigger → the runtime menu opens
 * and the Properties panel still reads 'Select a node on the canvas'." With no
 * layers panel, a node like that is unconfigurable and undeletable once dropped.
 *
 * The cause is not in that component. Any overlay primitive opens on
 * POINTER-DOWN and then puts `pointer-events: none` on the document body while
 * it is open, so by the time the `click` this canvas selects on is dispatched,
 * the element under the cursor is no longer the node — `closest('[data-node-id]')`
 * comes back null and the canvas clears the selection instead of making it. Any
 * component that opens on pointer-down has the same fate, so the fix is a
 * canvas-level rule rather than anything keyed to a component: run selection
 * FIRST, in the capture phase, before a runtime handler can react.
 *
 * `stopPropagation()` on the captured synthetic event is what makes the canvas
 * inert: React replays propagation itself, so stopping it at the canvas root
 * means the target's own `onPointerDown` never runs and the menu never opens
 * while the user is editing — the same argument as INERT_NAVIGATOR, one event
 * layer down.
 *
 * NOT `preventDefault()`: the browser default here is focus and the start of a
 * native drag gesture, and the canvas needs both (reorder is HTML5 drag).
 * Primary button only — a right-click must still reach the browser, and a
 * middle-click must not clear the selection.
 */
export function useCanvasPointerDown() {
  return (e: React.PointerEvent | React.MouseEvent) => {
    // `button` is absent on synthesised events in environments without a
    // PointerEvent constructor; a real browser always sets it, and treating
    // "unset" as primary keeps the guard from silently disabling selection.
    const button = (e as React.MouseEvent).button;
    if (typeof button === "number" && button !== 0) return;
    const id = nodeIdAt(e.target);
    // Over bare canvas there is nothing to suppress; let the click handler do
    // the clearing so a drag that starts on the background is unaffected.
    if (!id) return;
    e.stopPropagation();
    applySelection(id, e);
  };
}
