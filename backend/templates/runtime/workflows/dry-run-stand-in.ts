/**
 * What the build-time dry run puts where an earlier step's output would be.
 *
 * The dry run executes nothing, so a step's output is unknowable; a reference
 * into one is "supplied by the run", never "empty". This stand-in has to
 * answer ANY path to keep that promise — and it answered one level only.
 * `get` returned the string "dry-run" for every property, so
 * `{{load_rental.rows[0].listingId}}` walked rows → "dry-run", [0] → "d",
 * .listingId → undefined, and the dry run refused a correct workflow with
 * "WHERE id is empty". Reading a queried row is always at least that deep
 * (`db_query` returns `{ rows, count }`), so every such workflow was
 * refused (Neighbourhood Kit, UAT, 2026-09-18).
 *
 * Now every property answers with the stand-in itself, at any depth, and it
 * still reads as the string "dry-run" wherever a value is finally used.
 * Kept free of imports so a test can load exactly this object.
 */
export const STEP_OUTPUT: unknown = new Proxy(
  {},
  {
    get: (_t, prop) =>
      prop === "toString" || prop === Symbol.toPrimitive || prop === "valueOf"
        ? () => "dry-run"
        : STEP_OUTPUT,
  },
);

/**
 * Names a workflow's `set_variable` steps write. The engine stores the value
 * under `variableName`, not the node id, so the dry run seeds these beside the
 * node ids — otherwise `{{resolvedClinicId}}` set by one step and read by the
 * next is "empty" and a correct workflow is refused at assemble.
 */
export function setVariableNames(def: unknown): string[] {
  const d = def as any;
  const nodes: any[] = (d?.definition?.nodes ?? d?.nodes ?? []) as any[];
  return nodes
    .map((n) => n?.data?.config ?? n?.config ?? {})
    .filter((c) => c?.actionType === "set_variable" && typeof c.variableName === "string" && c.variableName)
    .map((c) => String(c.variableName));
}
