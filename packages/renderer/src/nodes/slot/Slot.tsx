/**
 * Slot — a placeholder a LAYOUT TEMPLATE fills via `applyLayout`. On a page
 * where no layout was applied there is nothing to fill it with, so it renders
 * nothing. The dispatcher wraps it in a StructuralNodeShell, so the author
 * still gets a labelled, selectable box on the canvas rather than a node that
 * exists only in the JSON on disk.
 *
 * THE WARNING USED TO BE A FLOOD.
 * ------------------------------
 * `console.warn` was called from inside the render body, unthrottled. One
 * unfilled Slot produced 4–6 messages per render pass; an audit session
 * captured **168** console messages of which nearly all were this one line.
 * That is worse than useless: it was simultaneously the only diagnosis the
 * author got (nothing appeared on the canvas) and loud enough to bury the
 * message they were actually looking for. React also runs render bodies twice
 * under StrictMode and re-runs them on every state change, so "once per render"
 * was never a meaningful rate.
 *
 * Warned once per slot name per process instead. The information content of the
 * second identical warning is zero.
 */
const warned = new Set<string>();

export function Slot({ node }: { node: any }) {
  const name = String(node?.props?.name ?? "default");
  if (!warned.has(name)) {
    warned.add(name);
    console.warn(`[renderer] unfilled slot '${name}'`);
  }
  return null;
}

/** Test seam — the warning is process-global, so a suite that asserts on it
 *  needs a way back to a clean slate. */
export function __resetSlotWarningsForTests(): void {
  warned.clear();
}
