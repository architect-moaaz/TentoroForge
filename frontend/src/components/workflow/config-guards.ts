/**
 * Guards for reading node config.
 *
 * WHY THIS EXISTS
 * Workflow `definition` is free-form JSON at the API boundary — the backend
 * stores node config without validating it (POSTing `inputMappings:
 * "not-an-array"` returns 201 {"saved": true}), and definitions are
 * LLM-generated. So a config field can be *any* JSON shape by the time the
 * editor reads it.
 *
 * The old pattern was `config.inputMappings ?? []`, which guards null and
 * undefined but NOT a wrong type, and not a bad row inside a good array. Both
 * threw during render — and because the properties panel is the ONLY screen
 * that can repair a broken config, a throw there left the user with no way to
 * fix it from the UI at all.
 *
 * Fixes UI-BUGS-FOUND.md A3-2, A4-1, A4-2, A4-3.
 */

/**
 * Read a config field that must be a list of objects.
 *
 * Returns `[]` for anything that is not an array, and drops entries that are
 * not plain objects. Both halves are load-bearing:
 *
 *   asObjectList("x")            → []            (A3-2, A4-1, A4-2)
 *   asObjectList([null, {a:1}])  → [{a:1}]       (A4-3)
 *
 * A4-3 is the reason an `Array.isArray` check alone is not enough: the array
 * can be well-formed and still contain a `null` row that every downstream
 * `.find(m => m.output === …)` dereferences.
 *
 * Dropping a malformed row rather than throwing is deliberate. The alternative
 * — surfacing an error — would still leave the panel unable to render, which is
 * the failure this guard exists to prevent. The rows that ARE readable stay
 * editable, so the user can repair the node and save a clean config over it.
 */
export function asObjectList<T>(value: unknown): T[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is T => typeof v === "object" && v !== null);
}
