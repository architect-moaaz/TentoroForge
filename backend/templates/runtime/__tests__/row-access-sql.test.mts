/**
 * FEEL-lite -> SQL for `row_access` rules.
 *
 * Runs the SHIPPED compiler and the SHIPPED FEEL-lite parser; only
 * `drizzle-orm` is stubbed, into a serializable tree the assertions read. So a
 * passing test here means the real parser produced an AST the real compiler
 * turned into the operators drizzle would have been handed.
 *
 * Run via __tests__/run-ownership-tests.sh. Exits non-zero on any failure.
 */

import { installHarness, eqJson, done } from "./_harness.mts";

const DRIZZLE = `
const c = (x) => (x && x.__col ? x.__col : x);
export const eq  = (a, b) => ({ op: "=",  l: c(a), r: c(b) });
export const ne  = (a, b) => ({ op: "!=", l: c(a), r: c(b) });
export const lt  = (a, b) => ({ op: "<",  l: c(a), r: c(b) });
export const lte = (a, b) => ({ op: "<=", l: c(a), r: c(b) });
export const gt  = (a, b) => ({ op: ">",  l: c(a), r: c(b) });
export const gte = (a, b) => ({ op: ">=", l: c(a), r: c(b) });
export const inArray = (a, vals) => ({ op: "in", l: c(a), r: vals });
export const isNull = (a) => ({ op: "isNull", l: c(a) });
export const isNotNull = (a) => ({ op: "isNotNull", l: c(a) });
export const and = (...x) => ({ op: "and", parts: x.filter(Boolean) });
export const or  = (...x) => ({ op: "or",  parts: x.filter(Boolean) });
export const not = (x) => ({ op: "not", part: x });
export function sql(strings) { return { op: "raw", text: strings.raw.join("?") }; }
sql.join = (parts) => ({ op: "raw", text: "join", parts });
`;

installHarness({ stubs: { "drizzle-orm": DRIZZLE } });

const { compileRowAccess } = await import("../rules/row-access-sql.ts");

// A Drizzle table is an object whose keys are its columns.
const applications: Record<string, any> = {};
for (const name of ["id", "currentStage", "status", "createdByUserId", "amount", "approvedAt", "isFlagged"]) {
  applications[name] = { __col: name };
}

const HM = { id: "user-hm", role: "hiring_manager" };

function eqShape(condition: string, expected: unknown, name: string, user: any = HM) {
  const r = compileRowAccess(condition, applications, user);
  eqJson(r.ok ? JSON.parse(JSON.stringify(r.where)) : { REFUSED: (r as any).reason },
         expected, name);
}
function rejects(condition: string, matcher: RegExp, name: string): void {
  const r = compileRowAccess(condition, applications, HM);
  eqJson(!r.ok && matcher.test(r.reason), true,
         `${name}${r.ok ? " (compiled when it should not)" : ` — ${(r as any).reason}`}`);
}

console.log("comparisons compile to drizzle operators");
{
  eqShape('status = "active"', { op: "=", l: "status", r: "active" }, "string equality");
  eqShape("amount >= 100", { op: ">=", l: "amount", r: 100 }, "numeric comparison");
  eqShape("amount > -5", { op: ">", l: "amount", r: -5 }, "negative literal");
  eqShape('"active" = status', { op: "=", l: "status", r: "active" },
    "a comparison written backwards is flipped, not rejected");
}

console.log("the acting user is a value, not a column");
{
  eqShape("createdByUserId = user.id", { op: "=", l: "createdByUserId", r: "user-hm" },
    "user.id resolves from the session");
  eqShape("createdByUserId = user.id", { op: "raw", text: "false" },
    "a session with no id can satisfy nothing", { role: "x" });
  // Called directly: `undefined` as a default-parameter argument would be
  // replaced by the default, which would test nothing.
  const anon = compileRowAccess("createdByUserId = user.id", applications, undefined);
  eqJson(anon.ok ? JSON.parse(JSON.stringify(anon.where)) : null, { op: "raw", text: "false" },
    "and neither can no session at all");
}

console.log("null is IS NULL, not = NULL");
{
  eqShape("approvedAt = null", { op: "isNull", l: "approvedAt" }, "= null");
  eqShape("approvedAt != null", { op: "isNotNull", l: "approvedAt" }, "!= null");
}

console.log("membership, ranges and combination");
{
  eqShape('currentStage in ["offer", "hired"]',
    { op: "in", l: "currentStage", r: ["offer", "hired"] }, "in a list of constants");
  eqShape("amount between 10 and 20",
    { op: "and", parts: [{ op: ">=", l: "amount", r: 10 }, { op: "<=", l: "amount", r: 20 }] },
    "between becomes a bounded pair");
  eqShape('not(status = "void")', { op: "not", part: { op: "=", l: "status", r: "void" } }, "not");
  eqShape("isFlagged", { op: "=", l: "isFlagged", r: true }, "a bare boolean column");
  eqShape("true", { op: "raw", text: "true" }, "`true` is how a role is granted every row");
}

console.log("the ats-live hiring-manager rule, as the builder would author it");
{
  // security.ownershipRules[5]: readable only while it is active at offer
  // stage, or where this manager recorded the decision.
  eqShape(
    '(currentStage = "offer" and status = "active") or createdByUserId = user.id',
    {
      op: "or",
      parts: [
        { op: "and", parts: [
          { op: "=", l: "currentStage", r: "offer" },
          { op: "=", l: "status", r: "active" },
        ] },
        { op: "=", l: "createdByUserId", r: "user-hm" },
      ],
    },
    "compiles whole, as one WHERE clause",
  );
}

console.log("what cannot become SQL is refused, with a reason");
{
  rejects('upper(status) = "ACTIVE"', /`upper\(…\)` cannot be compiled/, "a function call");
  rejects("amount * 2 > 100", /arithmetic/, "arithmetic");
  rejects('if status = "a" then 1 else 2', /if\/then\/else/, "if/then/else");
  rejects('nosuchcolumn = "x"', /not a column on this entity/, "a column that does not exist");
  rejects('order.total = 5', /reaches outside the row/, "reaching outside the row");
  rejects('"a" = "b"', /must name at least one column/, "two constants");
  rejects("", /empty/, "an empty condition");
  rejects('status = = "a"', /could not be parsed/, "a syntax error");
}

done("row-access-sql");
