/**
 * A person changes their own password through the engine's `set_password`
 * action: the current one checked, the new one hashed as sign-up hashes it,
 * a refusal in words — never a password column read or written by a step.
 * Runs the SHIPPED workflows/index.ts with its app-only imports stubbed.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
installHarness({
  stubs: {
    "@/db": `
      globalThis.__db = { rows: { 'u-1': { id: 'u-1', email: 'admin@example.com', password: 'h:admin1234' } }, writes: [] };
      export const db = {
        select: () => ({ from: () => ({ where: (w) => ({ limit: async () => { const r = globalThis.__db.rows[w.v]; return r ? [r] : []; } }) }) }),
        update: () => ({ set: (v) => ({ where: async (w) => { globalThis.__db.writes.push({ id: w.v, ...v }); } }) }),
        insert: () => ({ values: (v) => ({ returning: async () => [{ id: 'row-1', ...v }] }) }),
      };`,
    "bcryptjs": "export default { hash: async (p) => 'h:' + p, compare: async (p, h) => h === 'h:' + p };",
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "@/db/schema": "export const users = { __name: 'users', id: { __col: 'id', columnType: 'PgUUID', dataType: 'string' }, email: { columnType: 'PgText', dataType: 'string' }, password: { columnType: 'PgText', dataType: 'string' } };",
    "../ownership-rules": "export const ownershipRulesFor = () => [];",
    "drizzle-orm": "export const getTableName = (t) => t.__name; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = (c, v) => ({ op: 'eq', col: c && c.__col, v }); export const and = () => ({}); export const sql = () => ({}); export const ne = () => ({}); export const gt = () => ({}); export const gte = () => ({}); export const lt = () => ({}); export const lte = () => ({}); export const inArray = () => ({}); export const notInArray = () => ({});",
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
mod.registerDefaultActions();
const g: any = globalThis;
const setPassword = g.__handlers.set_password;
ok(typeof setPassword === "function", "the engine offers set_password");

// The engine holds the trigger's inputs in `variables`, where `{{name}}` reads them.
const asAdmin = (input: Record<string, unknown>): any =>
  ({ user: { id: "u-1", email: "admin@example.com" }, input, variables: { ...input }, log: [] });
const step = { currentPassword: "{{currentPassword}}", newPassword: "{{newPassword}}" };

let out = await setPassword(step, asAdmin({ currentPassword: "wrong", newPassword: "longer-secret" }));
eqJson([out.refused, out.message], [true, "The current password is not right."], "a wrong current password is refused in words");
eqJson(g.__db.writes, [], "and nothing is written");

out = await setPassword(step, { user: undefined, input: {}, variables: { newPassword: "longer-secret" }, log: [] });
eqJson(out.refused, true, "a signed-out visitor cannot change a password");

out = await setPassword(step, asAdmin({ currentPassword: "admin1234", newPassword: "abc" }));
eqJson(out.refused, true, "a password shorter than sign-up allows is refused");

out = await setPassword(step, asAdmin({ currentPassword: "admin1234", newPassword: "longer-secret" }));
eqJson(out, { changed: true }, "the right current password changes it");
eqJson(g.__db.writes, [{ id: "u-1", password: "h:longer-secret" }], "the new password is stored hashed, on the person's own row");
ok(!JSON.stringify(g.__db.writes).includes('"longer-secret"') || g.__db.writes[0].password.startsWith("h:"),
   "never the plain text");
done();
