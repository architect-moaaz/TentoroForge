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
check("many rows stay a list, and the first is readable as the record — as a template reads it",
  queryResult([member, { id: "m2" }]),
  { id: "m1", kycStatus: "verified", rows: [member, { id: "m2" }], count: 2, output: [member, { id: "m2" }] });
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

// AQUATRACK'S "SET DAILY GOAL" (m1dck85j): three active goals, and the
// condition asking whether there was one read `find_active_goal.id` as null.
const three = queryResult([{ id: "g1" }, { id: "g2" }, { id: "g3" }]);
check("a condition on a lookup that found several reads the first one's id",
  evaluateExpression("find_active_goal.id != null", { find_active_goal: three }), true);
check("and the list is still there to count",
  evaluateExpression("find_active_goal.rows.length > 0 and count(find_active_goal.rows) = 3", { find_active_goal: three }), true);

// A PATH ON A LIST: F&B's order total `sum(items.subtotal)` was 0.
check("a field read across a list is each item's value",
  evaluateExpression("sum(items.subtotal)", { items: [{ subtotal: 4.5 }, { subtotal: 3 }] }), 7.5);
check("and a single record's field reads as before",
  evaluateExpression("order.total", { order: { total: 12 } }), 12);

// TIME IS NOT TEXT: AquaTrack's Edit Log Entry (m1dck85j) added a day to a
// date and got "2026-10-1286400000", and `date and time(...)` read as `and`.
check("a day added to a date is the next date",
  evaluateExpression('date("2026-10-12") + duration("P1D")', {}), "2026-10-13");
check("a date held as text adds the same way",
  evaluateExpression('day + duration("P1D")', { day: "2026-10-31" }), "2026-11-01");
check("a moment less half an hour",
  evaluateExpression('at - duration("PT30M")', { at: "2026-10-12T08:30:00.000Z" }), "2026-10-12T08:00:00.000Z");
check("a moment from a database row (a Date) adds too",
  evaluateExpression('at + duration("P1D")', { at: new Date("2026-10-12T08:30:00.000Z") }), "2026-10-13T08:30:00.000Z");
check("date and time is one function, not a logical and",
  evaluateExpression('date and time("2026-10-12T08:30:00Z") + duration("PT1H")', {}), "2026-10-12T09:30:00.000Z");
check("two dates subtract to the time between",
  evaluateExpression('date("2026-10-13") - date("2026-10-12")', {}), 86400000);
check("text still joins text",
  evaluateExpression('"REF-" + n', { n: "0001" }), "REF-0001");

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
