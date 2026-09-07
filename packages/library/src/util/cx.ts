/**
 * Join class names, dropping the empty ones.
 *
 * WHY A SHARED ONE-LINER EXISTS
 * -----------------------------
 * Eight components declared `className` in their Zod schema and their node
 * schema, and then never destructured it: Tooltip, Popover, HoverCard, Drawer,
 * DataGrid, Timeline, OptimisticProvider and TableSortable. A producer — the
 * Figma mapper puts Tailwind on every node — writing `props.className` had it
 * silently discarded on all eight. The contract advertised a prop the component
 * provably dropped.
 *
 * The reason it kept happening is that each of these components hardwires its
 * own class string on its trigger element, so "accept className" is never a
 * plain `className={className}` — it is a merge, and a merge is the kind of
 * three-line thing everyone writes slightly differently or skips. One function,
 * so accepting the prop costs one call.
 *
 * The AUTHORED class comes last so it wins on conflicting Tailwind utilities,
 * which is the whole reason a producer sets it.
 */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter((p): p is string => typeof p === "string" && p.trim() !== "").join(" ");
}
