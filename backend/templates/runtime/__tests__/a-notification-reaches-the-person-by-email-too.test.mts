/**
 * A notification reaches the person by email too, and the test version lets
 * through the people the application invited.
 *
 * CARES (2026-11-24): approvers and requesters heard of a case only from the
 * bell, and testers read that as "email is not implemented"; and on the test
 * version a tester the administrator had invited got the invitation and then
 * nothing else. `send_notification` with `email` among its channels mails the
 * person (or every login in the role) through `send_email`, so the declared
 * mail service and the test version's rules apply; an address with an
 * invitation on record is let through on the test version.
 *
 * Runs the SHIPPED workflows/index.ts handlers.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
const g = globalThis as any;
g.__secrets = { SMTP_HOST: "smtp.test", SMTP_USER: "u", SMTP_PASSWORD: "p" };
g.__connected = {};
g.__persisted = [] as any[];
g.__mailed = [] as any[];
g.__invites = [{ email: "invited.gm@hotel.test" }];
g.__users = [
  { id: "u-gm1", email: "Invited.GM@hotel.test", accountType: "GeneralManager", isActive: true },
  { id: "u-gm2", email: "demo.gm@example.com", accountType: "GeneralManager", isActive: true },
  { id: "u-gm3", email: "gone.gm@hotel.test", accountType: "GeneralManager", isActive: false },
  { id: "u-desk", email: "desk@hotel.test", accountType: "Requester", isActive: true },
];

installHarness({
  stubs: {
    "@/db": "export const db = { select: () => ({ from: (t) => ({ where: (w) => { const rows = t.__name === 'users' ? globalThis.__users.filter((u) => w.op === 'eq' && (w.col === 'id' ? u.id === w.v : u.accountType === w.v)) : t.__name === 'forge_invites' ? globalThis.__invites.filter((i) => w.op === 'inArray' && w.v.includes(i.email)) : []; const p = Promise.resolve(rows); p.limit = async () => rows; return p; } }) }), insert: (t) => ({ values: (v) => { if (t.__name === 'forge_notifications') globalThis.__persisted.push(v); return { returning: async () => [{ ...v, id: 'n-' + globalThis.__persisted.length }], onConflictDoNothing: () => ({ returning: async () => [v] }), onConflictDoUpdate: async () => [v] }; } }), execute: async () => ({ rows: [] }) };",
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "@/db/schema": "export const forgeNotifications = { __name: 'forge_notifications' }; export const users = { __name: 'users', id: { __col: 'id' }, email: { __col: 'email' }, name: {}, accountType: { __col: 'accountType' }, isActive: {}, activeOrgId: {} }; export const forgeInvites = { __name: 'forge_invites', email: { __col: 'email' } };",
    "@/lib/account": "export const ROLES = ['Candidate', 'Organisation Admin', 'DITANS Operations', 'DITANS Identity Operations'];",
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
const notify = g.__handlers["send_notification"];
const ctx: any = { input: {}, variables: { __origin: "https://cares-test.example" }, log: [] };

console.log("a notification to a role, by email too");
const out = await notify({ actionType: "send_notification", channels: ["in_app", "email"], title: "A case waits for your decision",
                           message: "RF-12AB at Leicester Square", toRole: "GeneralManager", link: "/approvals" }, ctx);
const to = g.__mailed.map((m: any) => String(m.to));
eqJson(to.sort(), ["demo.gm@example.com", "invited.gm@hotel.test"], "every active login in the role is emailed, one message each");
ok(!to.includes("gone.gm@hotel.test"), "a switched-off login is not");
ok(String(g.__mailed[0].html).includes('<a href="https://cares-test.example/approvals">'), "the email opens the record in the application");
eqJson([out.sent, out.channel, out.emailed], [true, "in_app+email", 2], "the bell holds it and the step says it was emailed");
eqJson(g.__persisted.length, 1, "and the notification is kept once, not again for each email");

console.log("a notification to a role the process works out");
g.__mailed = [];
const stage = await notify({ actionType: "send_notification", channels: ["in_app", "email"], title: "A case waits", message: "x",
                             recipientRole: "{{nextRole}}" }, { ...ctx, variables: { ...ctx.variables, nextRole: "Requester" } });
eqJson([g.__mailed.map((m: any) => m.to), g.__persisted[g.__persisted.length - 1].role], [["desk@hotel.test"], "Requester"], "reaches that role, and the bell keeps the role, not the formula");

console.log("a notification to one person");
g.__mailed = [];
await notify({ actionType: "send_notification", channels: ["in_app", "email"], title: "Approved", message: "Your request was approved", to: "u-desk" }, ctx);
eqJson(g.__mailed.map((m: any) => m.to), ["desk@hotel.test"], "goes to that person's own address");

console.log("a notification without email among its channels");
g.__mailed = [];
const quiet = await notify({ actionType: "send_notification", title: "FYI", message: "x", to: "u-desk" }, ctx);
eqJson([g.__mailed.length, quiet.channel], [0, "in_app"], "emails nobody");

console.log("the test version");
process.env.FORGE_ENVIRONMENT = "test"; process.env.FORGE_TEST_RECIPIENTS = "owner@hotel.test";
g.__mailed = [];
const held = await notify({ actionType: "send_notification", channels: ["in_app", "email"], title: "A case waits", message: "x", toRole: "GeneralManager" }, ctx);
eqJson(g.__mailed.map((m: any) => m.to), ["invited.gm@hotel.test"], "lets through the person the application invited, and holds the demo address back");
eqJson([held.emailed, String(held.emailNotice).includes("the people this application invited")], [1, true], "and says what was held");
const other = await g.__handlers["send_email"]({ actionType: "send_email", to: "guest@outside.test", subject: "Hello", body: "Hi" }, ctx);
ok(other.sent === false && String(other.notice).includes("This is the test version"), "a guest who was never invited is still held");
const member = await g.__handlers["send_email"]({ actionType: "send_email", to: "owner@hotel.test", subject: "Hello", body: "Hi" }, ctx);
ok(member.sent === true, "and the organisation's own member is still emailed");
delete process.env.FORGE_ENVIRONMENT; delete process.env.FORGE_TEST_RECIPIENTS;

done("a notification reaches the person by email too");
