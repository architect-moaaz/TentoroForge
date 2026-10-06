/**
 * `_finalizeInsert` shapes a value map to what drizzle's driver mapping will
 * bind: a Date for a `timestamp()` column (dataType "date"), text for a
 * string-mode `date()` column (dataType "string"). Runs the SHIPPED
 * workflows/index.ts with its app-only imports stubbed.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
installHarness({
  stubs: {
    "@/db": "export const db = { insert: () => ({ values: (v) => ({ returning: async () => [{ id: 'row-1', ...v }] }) }) };",
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "@/db/schema": "export const cases = { __name: 'cases', id: { columnType: 'PgUUID', dataType: 'string' }, title: { columnType: 'PgText', dataType: 'string' }, caseNumber: { columnType: 'PgText', dataType: 'string' } };\nexport const carts = { __name: 'carts', id: { columnType: 'PgUUID', dataType: 'string' }, status: { columnType: 'PgText', dataType: 'string' }, guestToken: { columnType: 'PgText', dataType: 'string' } };",
    "../ownership-rules": "export const ownershipRulesFor = (e) => /^carts?$/.test(e) ? [{ entity: 'Cart', column: 'customerId', scope: 'user', guestColumn: 'guestToken' }] : [];",
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'cases'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = () => ({}); export const and = () => ({}); export const sql = () => ({});",
    "@/lib/error_reporter": "export const reportFromError = () => {};",
    "../fk-roles": "export const FK_ROLES = {}; export const fkRole = () => null; export const isDomainFk = () => false;",
    "@/lib/rules": "export const evaluateRuleSetForTable = async () => ({ errors: [], patches: {} });",
    "./engine": "globalThis.__handlers = {}; export const getActionHandler = (n) => globalThis.__handlers[n]; export const registerActionHandler = (n, h) => { globalThis.__handlers[n] = h; }; export const registerStepHandler = () => {}; export const executeWorkflow = async () => ({}); export const WorkflowEngine = class {}; export const getEngine = () => ({}); export const registerTriggerHandler = () => {}; export const runWorkflow = async () => ({});",
    "./ai": "export const registerAIActions = () => {};",
    "./ocr": "export const registerOcrActions = () => {};",
    "../events/emit-node": "export const makeEmitEventHandler = () => async () => ({});",
    "../feel-lite": "export const evaluateExpression = () => null;",
    "./types": noop,
    "fs": "export const promises = {}; export default { promises };",
    "path": "export default { join: (...a) => a.join('/'), resolve: (...a) => a.join('/') }; export const join = (...a) => a.join('/');",
  },
});

const mod: any = await import("../workflows/index.ts");
const _finalizeInsert = mod._finalizeInsert;
ok(typeof _finalizeInsert === "function", "the helper is exported for the test");

const table = {
  __name: "cases",
  title: { columnType: "PgText", dataType: "string" },
  dueDate: { columnType: "PgDateString", dataType: "string" },
  openedAt: { columnType: "PgDateString", dataType: "string" },
  createdAt: { columnType: "PgTimestamp", dataType: "date" },
};
const ctx: any = { user: undefined, variables: {} };

const out = _finalizeInsert(table, {
  title: "Late checkout fee disputed",
  dueDate: "2026-09-12",
  openedAt: new Date("2026-09-05T10:00:00.000Z"),
  createdAt: "2026-09-05T10:00:00.000Z",
}, ctx);

eqJson(out.dueDate, "2026-09-12", "a form's date string stays text for a string-mode date column");
eqJson(out.openedAt, "2026-09-05", "$now on a string-mode date column becomes the calendar date as text");
ok(out.createdAt instanceof Date, "a timestamp column receives a Date");
eqJson(out.title, "Late checkout fee disputed", "text is untouched");

// DEFECT-DEPLOY-CREATE: a Date reaching ANY string-typed column crashes
// postgres-js ("the string argument ... Received an instance of Date") and
// silently loses the record. `_resolveMap` coerces a pure ISO-date INPUT value
// to a Date; if that flows into a text/varchar column it used to pass raw. It
// must be stringified, not passed as a Date.
const outText = _finalizeInsert(table, {
  title: new Date("2026-09-05T10:00:00.000Z"),
}, ctx);
ok(typeof outText.title === "string",
   "a Date into a TEXT column is stringified, never passed raw to the driver");
eqJson(outText.title, "2026-09-05T10:00:00.000Z", "a text column takes the full ISO string");
const num = mod._numberIn;
eqJson([num("₹12,995"), num("20%"), num("$1,299.00"), num("1.299,50 €"), num("Rs. 4,999.50 only"), num("free")],
       [12995, 20, 1299, 1299.5, 4999.5, null], "the number in a price or a discount read off a page");
const priceTable = { __name: "p", price: { columnType: "PgNumeric", dataType: "string" },
                     discount: { columnType: "PgInteger", dataType: "number" }, note: { columnType: "PgText", dataType: "string" } };
eqJson(_finalizeInsert(priceTable, { price: "₹12,995", discount: "20%", note: "20% off" }, ctx),
       { price: "12995", discount: 20, note: "20% off" }, "a number column takes the number, a text column the text");
eqJson(_finalizeInsert(priceTable, { price: "call for price" }, ctx), {}, "text with no number is dropped, not the row");
const r0 = mod._resolveRef;
const photo: any = { variables: { analyze_image: { brand: null, productName: "French Press", category: "" }, count: 0 } };
eqJson(r0('{{analyze_image.brand ?? "Unbranded"}}', photo), "Unbranded", "a missing value takes its fallback");
eqJson(r0('{{analyze_image.productName ?? "Unnamed"}}', photo), "French Press", "a present value is kept");
eqJson(r0('{{analyze_image.category ?? analyze_image.productName ?? "Other"}}', photo), "French Press", "empty text is nothing; the next side is tried");
eqJson(r0('{{analyze_image.brand ?? 0}}', photo), 0, "a number literal stays a number");
eqJson(r0('Searching for {{analyze_image.brand ?? "any brand"}} {{analyze_image.productName}}', photo),
       "Searching for any brand French Press", "and inside text too");
const resolve = mod._resolveRef;
const a = resolve("$uuid", ctx), b = resolve("$uuid", ctx);
ok(typeof a === "string" && /^[0-9a-f-]{36}$/.test(a), "$uuid is a fresh identifier");
ok(a !== b, "each $uuid is its own");
ok(resolve("$now", ctx) instanceof Date, "$now is still a Date");

// The registered handler, against a stubbed database: the step's output is
// the row, so `{{insert_case.id}}` resolves, and `inserted` still does.
mod.registerDefaultActions();
const handlers: any = (globalThis as any).__handlers;
ok(typeof handlers.db_insert === "function", "db_insert is registered");
const ictx: any = { variables: { title: "Late checkout fee disputed" }, user: { id: "user-1" } };
const result = await handlers.db_insert(
  { table: "cases", values: { title: "{{title}}", caseNumber: "$uuid" }, __nodeId: "insert_case" }, ictx,
);
eqJson(result.id, "row-1", "the step's output carries the row's id at the top");
eqJson(result.inserted.id, "row-1", "`inserted` still carries the row");
eqJson(resolve("{{insert_case.id}}", { variables: { insert_case: result } }), "row-1", "{{insert_case.id}} walks into it");

// A GUEST'S CART CARRIES THEIR TOKEN (TCommerce, 2026-10-06). The execute
// route puts the visitor's `forge-guest` token in `__guest`; an insert into a
// table whose ownership rule names a guestColumn stamps it — over anything the
// step said — so the data engine can hand the cart back to that visitor.
const GUEST = "6f1c2b8e-0000-4000-8000-000000000001";
const asGuest = await handlers.db_insert(
  { table: "carts", values: { status: "open", guestToken: "someone-else" } },
  { variables: { __guest: GUEST } } as any,
);
eqJson(asGuest.inserted.guestToken, GUEST, "a guest's insert is stamped with their own token");
const signedIn = await handlers.db_insert(
  { table: "carts", values: { status: "open" } },
  { variables: { __guest: GUEST }, user: { id: "user-1" } } as any,
);
ok(signedIn.inserted.guestToken === undefined, "a signed-in person's cart is theirs by customer, not stamped");
const other = await handlers.db_insert(
  { table: "cases", values: { title: "x" } }, { variables: { __guest: GUEST } } as any,
);
ok(!("guestToken" in other.inserted), "a table with no guestColumn is left alone");
eqJson(resolve("$guest", { variables: { __guest: GUEST } } as any), GUEST, "$guest names the visitor's token");
eqJson(resolve("$guest", { variables: {} } as any), null, "and nothing when there is none");
done("insert-binding");
