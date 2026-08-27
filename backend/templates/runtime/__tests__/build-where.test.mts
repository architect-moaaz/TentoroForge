/**
 * Standalone test for _buildWhere — the WHERE-clause resolver used by every
 * db_update / db_delete / db_query workflow node.
 *
 * Regression: an unresolved WHERE ref used to reach Postgres as an empty
 * string, triggering "22P02 invalid input syntax for type uuid: ''" on typed
 * columns. On UNTYPED columns it would have matched every row — silent data
 * loss on db_delete. The fixed function throws with a descriptive message.
 *
 * Following the same standalone pattern as resolve-aggregate.test.mts:
 * inline the helpers so we don't depend on drizzle-orm / a package.json.
 * Run with: tsx or node --experimental-vm-modules
 * Exits 0 on pass, 1 on any failure.
 */

// ── Inline the resolver + fixture types ─────────────────────────────────────

type WorkflowExecutionContext = { variables: Record<string, unknown> };

// Stub `eq` and `and` — the real ones return drizzle SQL nodes; for testing
// we just return a serializable marker so the assertions can inspect the tree.
const eq = (col: unknown, val: unknown) => ({ kind: "eq", col, val });
const and = (...conds: unknown[]) => ({ kind: "and", conds });

// ── _resolveRef inlined from workflows/index.ts (unchanged) ─────────────────

function _resolveRef(ref: unknown, ctx: WorkflowExecutionContext): unknown {
  if (typeof ref !== "string") return ref;
  const braces = /^\{\{([^}]+)\}\}$/.exec(ref);
  if (braces) {
    const path = braces[1].trim();
    const parts = path.split(".");
    let cur: unknown = ctx.variables[parts[0]];
    for (let i = 1; i < parts.length && cur != null; i++) {
      cur = (cur as Record<string, unknown>)[parts[i]];
    }
    return cur == null ? "" : cur;
  }
  if (Object.prototype.hasOwnProperty.call(ctx.variables, ref)) return ctx.variables[ref];
  return ref;
}

// ── _buildWhere — the CURRENT (fixed) implementation, mirrored verbatim ─────

function _buildWhere(table: any, where: unknown, ctx: WorkflowExecutionContext): any {
  if (!where || typeof where !== "object") return undefined;
  const entries = Object.entries(where as Record<string, unknown>);
  const dropped: string[] = [];
  const conds = entries
    .map(([field, ref]) => {
      if (!table[field]) { dropped.push(field); return undefined; }
      const v = _resolveRef(ref, ctx);
      if (v === "" || v == null) {
        throw new Error(
          `WHERE ${field} is empty — trigger form is missing an input for this workflow node`,
        );
      }
      return eq(table[field], v);
    })
    .filter(Boolean) as any[];
  if (conds.length === 0) {
    throw new Error(
      `WHERE resolved to zero conditions — ${entries.length === 0 ? "empty {} config" : `no config field matched the table (dropped: ${dropped.join(", ")})`}`,
    );
  }
  return conds.length === 1 ? conds[0] : and(...conds);
}

// ── Assertions ──────────────────────────────────────────────────────────────

let failed = 0;
function assert(cond: unknown, msg: string): void {
  if (cond) { console.log(`  ✓ ${msg}`); return; }
  console.error(`  ✗ ${msg}`); failed++;
}
function assertThrows(fn: () => unknown, matcher: RegExp, msg: string): void {
  try { fn(); console.error(`  ✗ ${msg} (expected throw)`); failed++; }
  catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (matcher.test(message)) console.log(`  ✓ ${msg}`);
    else { console.error(`  ✗ ${msg} — got: ${message}`); failed++; }
  }
}

const idCol = { name: "id" };
const table = { id: idCol };

// ── 1. Happy path: resolved id → eq(id, uuid) ───────────────────────────────
console.log("_buildWhere: resolves a supplied id");
{
  const ctx = { variables: { appointmentId: "11111111-2222-3333-4444-555555555555" } };
  const w = _buildWhere(table, { id: "{{appointmentId}}" }, ctx);
  assert(w && w.kind === "eq", "returns an eq(...) condition");
  assert(w.val === "11111111-2222-3333-4444-555555555555", "eq.val === the resolved uuid");
}

// ── 2. Regression: missing ref must throw, not reach Postgres ───────────────
console.log("_buildWhere: throws when the WHERE ref is unresolved ('' from missing var)");
{
  const ctx = { variables: {} }; // appointmentId never set
  assertThrows(
    () => _buildWhere(table, { id: "{{appointmentId}}" }, ctx),
    /WHERE id is empty/,
    "throws 'WHERE id is empty' with the offending field name",
  );
}

// ── 3. Explicit null / undefined variable is also caught ────────────────────
console.log("_buildWhere: throws when the variable is explicitly null or undefined");
{
  const ctxNull = { variables: { appointmentId: null } };
  const ctxUndef = { variables: { appointmentId: undefined } };
  assertThrows(
    () => _buildWhere(table, { id: "{{appointmentId}}" }, ctxNull),
    /WHERE id is empty/,
    "throws on null variable",
  );
  assertThrows(
    () => _buildWhere(table, { id: "{{appointmentId}}" }, ctxUndef),
    /WHERE id is empty/,
    "throws on undefined variable",
  );
}

// ── 4. Empty-string literal in the WHERE map also caught ────────────────────
console.log("_buildWhere: throws on empty-string literal");
{
  assertThrows(
    () => _buildWhere(table, { id: "" }, { variables: {} }),
    /WHERE id is empty/,
    "throws on empty-string literal",
  );
}

// ── 5. Config had fields but none survived → throw (was: silent drop) ───────
// REGRESSION: when every field in the WHERE config drifted from the table
// schema (snake_case vs camelCase, renamed column, whatever), _buildWhere used
// to return undefined — and db_update/db_delete would then run UNFILTERED,
// wiping the entire table. Failing loudly here is the guardrail.
console.log("_buildWhere: throws when config had fields but none matched the table");
{
  const ctx = { variables: { x: "abc" } };
  assertThrows(
    () => _buildWhere(table, { unknownField: "{{x}}" }, ctx),
    /WHERE resolved to zero conditions/,
    "throws when every config field is filtered out",
  );
}

// ── 5b. Explicitly-empty WHERE object is still a caller mistake ─────────────
console.log("_buildWhere: throws when WHERE is an empty object");
{
  assertThrows(
    () => _buildWhere(table, {}, { variables: {} }),
    /WHERE resolved to zero conditions/,
    "throws on {} config",
  );
}

// ── 5c. Missing WHERE entirely stays undefined — CALLER's responsibility ────
// The handlers themselves must refuse to run an unfiltered UPDATE/DELETE;
// _buildWhere at the pure-function level accepts "no config" as "no filter".
console.log("_buildWhere: returns undefined when no WHERE config given");
{
  const w = _buildWhere(table, undefined, { variables: {} });
  assert(w === undefined, "undefined stays undefined (handler-level guard covers this)");
}

// ── 6. Multi-field WHERE reaches `and(...)` when all resolve ────────────────
console.log("_buildWhere: combines multiple resolved fields with and()");
{
  const t = { id: { name: "id" }, status: { name: "status" } };
  const ctx = { variables: { id: "abc", status: "open" } };
  const w = _buildWhere(t, { id: "{{id}}", status: "{{status}}" }, ctx);
  assert(w && w.kind === "and", "returns an and(...) node when >1 condition");
  assert(Array.isArray(w.conds) && w.conds.length === 2, "and() carries both conditions");
}

// ── 7. Falsy-but-legal values (0, "false") are NOT treated as empty ─────────
console.log("_buildWhere: preserves legal falsy values (0, 'false')");
{
  const t = { count: { name: "count" }, isActive: { name: "isActive" } };
  const ctx = { variables: { c: 0, a: "false" } };
  const w = _buildWhere(t, { count: "{{c}}", isActive: "{{a}}" }, ctx);
  // 0 → resolves to 0, isActive → "false" (both legal non-empty)
  assert(w && w.kind === "and", "and() returned");
  const counts = w.conds.filter((c: any) => c.col === t.count);
  assert(counts.length === 1 && counts[0].val === 0, "count=0 preserved");
}

// ── Result ──────────────────────────────────────────────────────────────────
if (failed === 0) { console.log("\nAll _buildWhere tests passed."); process.exit(0); }
console.error(`\n${failed} test(s) failed.`); process.exit(1);
