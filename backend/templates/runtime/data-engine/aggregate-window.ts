// Pure date-window math for op:"aggregate" metrics. Kept dependency-free (no
// db, no drizzle-orm) so both data-engine.ts and its unit tests can import the
// SAME implementation — the week/month boundary logic is the part most prone to
// subtle bugs, so it must be tested against the real code, not a copy.

export type AggregateWindow = "today" | "week" | "month";

/** Midnight of the window's start, or null when no window is specified.
 *  - today: midnight today
 *  - week:  midnight on the most recent Sunday (local)
 *  - month: midnight on the 1st of the current month */
export function windowStart(window?: string): Date | null {
  if (!window) return null;
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  if (window === "today") return d;
  if (window === "week") { d.setDate(d.getDate() - d.getDay()); return d; }
  if (window === "month") { d.setDate(1); return d; }
  return null;
}

/** The window immediately BEFORE the current one, as a half-open [start, end)
 *  range whose `end` is exactly the current window's start. Used by period-delta
 *  metrics to compare "this period" against "last period".
 *   - today: yesterday 00:00   → today 00:00
 *   - week:  previous Sunday   → this Sunday
 *   - month: 1st of last month → 1st of this month
 *  Returns null when no (or an unknown) window is given. */
export function priorWindow(window?: string): { start: Date; end: Date } | null {
  const end = windowStart(window);
  if (!end) return null;
  const start = new Date(end);
  if (window === "today") start.setDate(start.getDate() - 1);
  else if (window === "week") start.setDate(start.getDate() - 7);
  else if (window === "month") start.setMonth(start.getMonth() - 1);
  else return null;
  return { start, end };
}
