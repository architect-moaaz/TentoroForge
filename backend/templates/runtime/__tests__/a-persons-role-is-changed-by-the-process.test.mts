/**
 * A person's role is changed by the process, and the change holds from their
 * next sign-in.
 *
 * CARES' administrator could invite someone in a role and never move them to
 * another (2026-11-24): the role a login holds lives in `users`, which no
 * workflow may write. `set_account_role` moves a login to a declared role and
 * ends its open sessions (sessionVersion), never touches anyone's own role,
 * and refuses a role the application does not declare.
 *
 * Runs the SHIPPED workflows/index.ts set_account_role handler.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
const g = globalThis as any;
g.__secrets = {};
g.__connected = {};
g.__persisted = [] as any[];
g.__mailed = [] as any[];
g.__updates = [] as any[];
g.__invites = [] as any[];
g.__users = [
  { id: "u-admin", email: "admin@cares.test", accountType: "Administrator", sessionVersion: 0 },
  { id: "u-desk", email: "desk@cares.test", accountType: "Requester", sessionVersion: 2 },
];

installHarness({
  stubs: {
    "@/db": "export const db = { select: () => ({ from: (t) => ({ where: (w) => ({ limit: async () => globalThis.__users.filter((u) => (w && w.op === 'eq') ? u.id === w.v : u.email === globalThis.__lookup) }) }) }), update: (t) => ({ set: (v) => ({ where: async (w) => { globalThis.__updates.push({ id: w.v, set: v }); const u = globalThis.__users.find((x) => x.id === w.v); if (u) { for (const [k, val] of Object.entries(v)) u[k] = (val && val.__sql) ? (Number(u[k] ?? 0) + 1) : val; } return []; } }) }), insert: () => ({ values: (v) => ({ onConflictDoNothing: () => ({ returning: async () => [v] }), onConflictDoUpdate: async () => [v], returning: async () => [v] }) }), execute: async () => ({ rows: [] }) };",
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "@/db/schema": "export const forgeNotifications = { __name: 'forge_notifications' }; export const users = { __name: 'users', id: { __col: 'id' }, email: { __col: 'email' }, name: {}, accountType: {}, isActive: {}, activeOrgId: {}, sessionVersion: { __col: 'session_version' } }; export const forgeInvites = { __name: 'forge_invites', email: { __col: 'email' }, orgId: {} };",
    "@/lib/account": "export const ROLES = ['Requester', 'FrontOfficeManager', 'GeneralManager', 'Administrator'];",
    bcryptjs: "export default { hash: async (s) => '$2b$12$unusable-' + s.length };",
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'x'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = (c, v) => ({ op: 'eq', col: c && c.__col, v }); export const and = (...p) => ({ op: 'and', parts: p }); export const sql = (s, ...v) => { globalThis.__lookup = v[1]; return { __sql: [s, v] }; }; export const ne = (c, v) => ({ op: 'ne', col: c && c.__col, v }); export const gt = (c, v) => ({ op: 'gt', col: c && c.__col, v }); export const gte = (c, v) => ({ op: 'gte', col: c && c.__col, v }); export const lt = (c, v) => ({ op: 'lt', col: c && c.__col, v }); export const lte = (c, v) => ({ op: 'lte', col: c && c.__col, v }); export const inArray = (c, v) => ({ op: 'inArray', col: c && c.__col, v }); export const notInArray = (c, v) => ({ op: 'notInArray', col: c && c.__col, v });",
    "@/lib/error_reporter": "export const reportFromError = () => {};",
    "../fk-roles": "export const FK_ROLES = {}; export const fkRole = () => null; export const isDomainFk = () => false;",
    "@/lib/rules": "export const evaluateRuleSetForTable = async () => ({ errors: [], patches: {} });",
    "@/lib/integrations/resolver": "export const getSecret = async (_p, k) => globalThis.__secrets[k]; export const clearSecretCache = () => {};",
    "@/lib/integrations/connected": "export const connectedService = (a) => globalThis.__connected[a]; export const CONNECTED_SERVICES = globalThis.__connected;",
    // nodemailer is CommonJS: Node's interop gives the shipped code a named
    // `createTransport` as well as a default, and it calls the named one.
    nodemailer: "export const createTransport = () => ({ sendMail: async (m) => { globalThis.__mailed.push(m); return { messageId: 'mid-1' }; } }); export default { createTransport };",
    "./engine": "globalThis.__handlers = {}; export const getActionHandler = (n) => globalThis.__handlers[n]; export const registerActionHandler = (n, h) => { globalThis.__handlers[n] = h; }; export const registerStepHandler = () => {}; export const executeWorkflow = async () => ({}); export const WorkflowEngine = class {}; export const getEngine = () => ({}); export const registerTriggerHandler = () => {}; export const runWorkflow = async () => ({});",
    "./ai": "export const registerAIActions = () => {};",
    "./ocr": "export const registerOcrActions = () => {};",
    "../events/emit-node": "export const makeEmitEventHandler = () => async () => ({});",
    "../feel-lite": "export const evaluateExpression = () => null;",
    "./types": noop,
    fs: "export const promises = {}; export default { promises };",
    path: "export default { join: (...a) => a.join('/'), resolve: (...a) => a.join('/') }; export const join = (...a) => a.join('/');",
  },
});

const mod: any = await import("../workflows/index.ts");
mod.registerDefaultActions();
const change = g.__handlers["set_account_role"];
ok(typeof change === "function", "set_account_role is registered");
const ctx: any = { input: {}, variables: { __user: { id: "u-admin" }, person: "u-desk", newRole: "FrontOfficeManager" }, log: [] };

console.log("an administrator moves the desk to Front Office Manager");
const moved = await change({ actionType: "set_account_role", userId: "{{person}}", role: "{{newRole}}" }, ctx);
eqJson([moved.changed, moved.userId, moved.role, moved.previous], [true, "u-desk", "FrontOfficeManager", "Requester"], "the login is moved, and says from what");
const desk = g.__users.find((u: any) => u.id === "u-desk");
eqJson(desk.accountType, "FrontOfficeManager", "the login now holds the new role");
eqJson(desk.sessionVersion, 3, "and its open sessions end, so the new role holds from the next sign-in");

console.log("the same role again");
const before = g.__updates.length;
const same = await change({ actionType: "set_account_role", userId: "u-desk", role: "FrontOfficeManager" }, ctx);
eqJson([same.changed, g.__updates.length - before], [false, 0], "changes nothing and signs nobody out");

console.log("by e-mail");
const byMail = await change({ actionType: "set_account_role", email: " Desk@CARES.test ", role: "GeneralManager" }, ctx);
eqJson([byMail.changed, byMail.userId, desk.accountType], [true, "u-desk", "GeneralManager"], "finds the login by its address");

console.log("what is refused");
const undeclared = await change({ actionType: "set_account_role", userId: "u-desk", role: "Owner" }, ctx);
ok(String(undeclared.error).includes("is not one of this application's roles") && desk.accountType === "GeneralManager", "a role the application does not declare, with nothing changed");
const nobody = await change({ actionType: "set_account_role", userId: "u-ghost", role: "Requester" }, ctx);
ok(String(nobody.error).includes("there is no login for u-ghost"), "a login that does not exist");
const self = await change({ actionType: "set_account_role", userId: "u-admin", role: "Requester" }, ctx);
ok(String(self.error).includes("cannot change their own role") && g.__users[0].accountType === "Administrator", "a person changing their own role — the last administrator cannot take themselves out");
const unnamed = await change({ actionType: "set_account_role", role: "Requester" }, ctx);
ok(String(unnamed.error).includes("name the person's `userId` or `email`"), "a step that names nobody");

done("a person's role is changed by the process");
