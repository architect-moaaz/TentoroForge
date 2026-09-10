/**
 * THE ELEMENT A NODE ACTUALLY OCCUPIES SPACE AS.
 *
 * `LibraryDispatcher` wraps every library component in a `display: contents`
 * span. A contents element generates no box at all: `getBoundingClientRect()`
 * on it is 0x0, `draggable` on it starts no drag, and an overlay drawn over it
 * covers nothing. The audit reported the symptom on Spinner — "the dispatcher
 * wrapper measures 0x0 with display: contents while the actual spinner inside
 * is 24x24, so the selectable box the canvas draws for the node has no area" —
 * but the wrapper is on all 133 components, so every canvas feature that
 * measures a node has to walk past it.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * Six of them did, in six copies: SelectionOverlay, DropIndicator,
 * ReorderIndicator, useDrop, empty-hints and Canvas — each with its own private
 * `walker`/`resolveBoxEl`/`resolveLayoutBox`, three of them literally the same
 * eleven lines. They had already drifted: Canvas looked at exactly ONE level
 * (`:scope > *`) and did not check whether that child was itself
 * `display: contents`, so a component that nests a second contents wrapper got
 * `draggable` set on another boxless element and could not be dragged at all —
 * a divergence nobody could see, in the copy that had no test.
 *
 * One function, one behaviour, six call sites. A seventh feature that needs to
 * measure a node gets the fixed version for free.
 */

/**
 * Walk through any `display: contents` wrappers to the first descendant that
 * generates a layout box.
 *
 * Returns the element itself when it is already a box, and `null` when the
 * subtree is contents all the way down (a node that renders nothing — which is
 * a real state on this canvas, not an impossible one). Depth-first and in
 * document order, so the box returned is the visually first one.
 *
 * `getComputedStyle` is guarded because this runs in jsdom and in SSR-shaped
 * test environments where it may not exist; there, the element is returned
 * unchanged rather than the walk silently reporting "no box".
 */
export function resolveLayoutBox(el: HTMLElement | null): HTMLElement | null {
  if (!el) return null;
  if (typeof getComputedStyle !== "function") return el;
  if (getComputedStyle(el).display !== "contents") return el;
  for (const child of Array.from(el.children) as HTMLElement[]) {
    const inner = resolveLayoutBox(child);
    if (inner) return inner;
  }
  return null;
}

/** `resolveLayoutBox` for a node id, scoped to a canvas root. */
export function resolveNodeBox(
  canvas: HTMLElement | null,
  nodeId: string,
): HTMLElement | null {
  return resolveLayoutBox(
    canvas?.querySelector<HTMLElement>(`[data-node-id="${nodeId}"]`) ?? null,
  );
}
