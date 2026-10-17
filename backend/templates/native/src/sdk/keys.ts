// The app SDK (native) — stable keys for what a hook depends on.
//
// A read hook is handed an options object written inline in a screen:
// `useList("Order", { where: { status: "open" }, sort: "total" })`. That object
// is a NEW object on every render, so an effect keyed on it re-runs on every
// render, which sets state, which renders again — a loop that hammers the
// server. The hook keys its effect on `stableKey(options)` instead: the same
// content is the same key, whatever order its keys were written in.
//
// PURE — no react-native import.

/** The content of a value as a string: object keys sorted, `undefined` left
 *  out (as JSON does), dates as ISO. Two values that mean the same give the
 *  same key. */
export function stableKey(value: unknown): string {
  return JSON.stringify(normalise(value)) ?? "undefined";
}

function normalise(value: unknown): unknown {
  if (value instanceof Date) return value.toISOString();
  if (Array.isArray(value)) return value.map((v) => (v === undefined ? null : normalise(v)));
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(value as Record<string, unknown>).sort()) {
      const v = (value as Record<string, unknown>)[k];
      if (v !== undefined && typeof v !== "function") out[k] = normalise(v);
    }
    return out;
  }
  return value;
}
