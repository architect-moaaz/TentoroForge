/**
 * A lookup of one record reads as that record.
 *
 * Run (Node 25+ with built-in type stripping):
 *   cd backend/templates/runtime && \
 *   node --experimental-strip-types __tests__/query-result.test.mts
 */
import { queryResult } from "../workflows/query-result.ts";

let passed = 0, failed = 0;
const check = (name: string, actual: unknown, expected: unknown) => {
  if (JSON.stringify(actual) === JSON.stringify(expected)) { passed++; console.log(`  ✓ ${name}`); }
  else { failed++; console.log(`  ✗ ${name}\n      expected: ${JSON.stringify(expected)}\n      actual:   ${JSON.stringify(actual)}`); }
};

const member = { id: "m1", kycStatus: "verified" };

check("one row is readable as the record a condition asks about",
  queryResult([member]), { id: "m1", kycStatus: "verified", rows: [member], count: 1, output: [member] });
check("no rows is a count of nothing, and no fields to read",
  queryResult([]), { rows: [], count: 0, output: [] });
check("many rows stay a list — there is no single record to be",
  queryResult([member, { id: "m2" }]), { rows: [member, { id: "m2" }], count: 2, output: [member, { id: "m2" }] });
check("a column called rows does not shadow the list",
  queryResult([{ id: "r1", rows: "some text" }]),
  { id: "r1", rows: [{ id: "r1", rows: "some text" }], count: 1, output: [{ id: "r1", rows: "some text" }] });
check("nothing at all is still an answer of the right shape",
  queryResult(undefined), { rows: [], count: 0, output: [] });

// THE DUPLICATE CHECK F&B WROTE: `count(check_existing.output) > 0` refused every
// new category — `output` was not on a query's result, and count(nothing) was 1.
const { evaluateExpression } = await import("../feel-lite/index.ts");
check("a query with no rows is no duplicate",
  evaluateExpression("count(check_existing.output) > 0", { check_existing: queryResult([]) }), false);
check("a query with a row is one",
  evaluateExpression("count(check_existing.output) > 0", { check_existing: queryResult([member]) }), true);
check("count of nothing is none",
  evaluateExpression("count(missing)", {}), 0);

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
