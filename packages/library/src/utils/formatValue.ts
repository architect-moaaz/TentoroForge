/**
 * Coerce ANY bound value into a safe, display-ready string.
 *
 * Bound rows routinely hand components a value whose type the schema didn't
 * predict — a Date object, a number, a boolean, null, even a nested object. Passed
 * straight to JSX as a child, a non-primitive throws
 * `Objects are not valid as a React child (found: [object Date])` and takes down
 * the whole subtree. Every value-rendering component should funnel through this so
 * that can never happen.
 *
 * Dates are formatted **deterministically** (ISO `YYYY-MM-DD`), NOT via
 * `toLocaleDateString()`, on purpose: locale-dependent formatting differs between
 * the server and the browser and triggers React hydration mismatches.
 */
export function formatValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? "" : value.toISOString().slice(0, 10);
  }
  // An ISO-ish date string that arrived as a Date-shaped object is handled above;
  // anything else object-like is stringified safely rather than crashing render.
  if (typeof value === "object") {
    try {
      const s = JSON.stringify(value);
      return s === "{}" || s === "[]" ? "" : s;
    } catch {
      return "";
    }
  }
  return String(value);
}

/** True when a string is a bare UUID — used to avoid showing raw ids as labels. */
export function isUuid(value: unknown): boolean {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
  );
}
