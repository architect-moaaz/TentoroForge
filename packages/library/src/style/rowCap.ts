/**
 * How many rows a list renders when something sits beside it.
 *
 * The dashboard composer decides the cap (a grid row is as tall as its
 * tallest child, so an unbounded feed strands the space next to it) and
 * writes `limit` onto the node. This is the other half of that contract: the
 * components that receive it.
 *
 * A zero or negative limit means "no limit", not "render nothing" — a mis-set
 * value should never be able to blank a card, because an empty card reads as
 * a broken one and the cause is invisible.
 */
export function applyRowCap<T>(rows: T[], limit?: number): T[] {
  if (!Array.isArray(rows)) return [];
  const n = typeof limit === "string" ? parseInt(limit, 10) : limit;
  if (typeof n !== "number" || !Number.isFinite(n) || n <= 0) return rows;
  return rows.slice(0, n);
}
