/**
 * A login for someone else is made by the process, never by a person typing it.
 *
 * DITANS operations could not add a member of staff (2026-11-22): "Invite
 * user" ran a process that wrote a staff record and emailed "sign in with this
 * work email" — there was no account, so there was nothing to sign in to, and
 * every employer waited on a verification nobody could give. `invite_account`
 * makes the account (inactive, a password nobody knows), keeps only the digest
 * of a one-time link, and emails that link.
 *
 * Runs the SHIPPED workflows/index.ts invite_account handler.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
const g = globalThis as any;
g.__secrets = { SMTP_HOST: "smtp.test", SMTP_USER: "u", SMTP_PASS: "p" };
g.__connected = {};
g.__persisted = [] as any[];
g.__mailed = [] as any[];
g.__users = [{ id: "u-0", email: "already@ditans.test", accountType: "Candidate" }];
g.__invites = [] as any[];

installHarness({
  stubs: {
    "@/db": "export const db = { select: () => ({ from: (t) => ({ where: (w) => ({ limit: async () => (t.__name === 'users' ? globalThis.__users.filter((u) => u.email === globalThis.__lookup) : []) }) }) }), insert: (t) => ({ values: (v) => { const done = { onConflictDoNothing: () => ({ returning: async () => { if (t.__name === 'users') { const row = { ...v, id: 'u-' + (globalThis.__users.length + 1) }; globalThis.__users.push(row); return [row]; } return [v]; } }), onConflictDoUpdate: async () => { globalThis.__invites.push(v); return [v]; }, returning: async () => [{ ...v, id: 'n-1' }] }; if (t.__name === 'forge_notifications') globalThis.__persisted.push(v); return done; } }), execute: async () => ({ rows: [] }) };",
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "@/db/schema": "export const forgeNotifications = { __name: 'forge_notifications' }; export const users = { __name: 'users', email: { __col: 'email' }, name: {}, accountType: {}, isActive: {}, activeOrgId: {} }; export const forgeInvites = { __name: 'forge_invites', email: { __col: 'email' }, orgId: {} };",
    "@/lib/account": "export const ROLES = ['Candidate', 'Organisation Admin', 'DITANS Operations', 'DITANS Identity Operations'];",
    bcryptjs: "export default { hash: async (s) => '$2b$12$unusable-' + s.length };",
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'x'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = () => ({}); export const and = (...p) => ({ op: 'and', parts: p }); export const sql = (s, ...v) => { globalThis.__lookup = v[1]; return { __sql: [s, v] }; }; export const ne = (c, v) => ({ op: 'ne', col: c && c.__col, v }); export const gt = (c, v) => ({ op: 'gt', col: c && c.__col, v }); export const gte = (c, v) => ({ op: 'gte', col: c && c.__col, v }); export const lt = (c, v) => ({ op: 'lt', col: c && c.__col, v }); export const lte = (c, v) => ({ op: 'lte', col: c && c.__col, v }); export const inArray = (c, v) => ({ op: 'inArray', col: c && c.__col, v }); export const notInArray = (c, v) => ({ op: 'notInArray', col: c && c.__col, v });",
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
const invite = g.__handlers["invite_account"];
ok(typeof invite === "function", "invite_account is registered");

const ctx: any = { input: {}, variables: { __origin: "https://app.test", staffRole: "DITANS Identity Operations", fullName: "Sara Ali" }, log: [] };
const step = { actionType: "invite_account", email: " Sara.Ali@DITANS.test ", name: "{{fullName}}", role: "{{staffRole}}",
               subject: "You're invited to DITANS operations", body: "Hi {{fullName}}, you have been invited to DITANS as a staff member." };

console.log("a new person");
const made = await invite(step, ctx);
eqJson([made.invited, made.email, made.emailed], [true, "sara.ali@ditans.test", true], "gets an account, by their address in lower case, and an email");
const row = g.__users.find((u: any) => u.email === "sara.ali@ditans.test");
eqJson([row.accountType, row.name, row.isActive], ["DITANS Identity Operations", "Sara Ali", false], "in the role resolved from the process, inactive until a password is chosen");
ok(String(row.password).startsWith("$2b$12$"), "with a password nobody knows (a hash of a random value), never one the process holds");
const inv = g.__invites[0];
eqJson([inv.email, inv.purpose, inv.usedAt], ["sara.ali@ditans.test", "invite", null], "a one-time invite is kept for that address");
const mail = g.__mailed[0];
eqJson(mail.to, "sara.ali@ditans.test", "the email goes to the person");
const link = (String(mail.text ?? mail.html ?? "").match(/https:\/\/app\.test\/set-password\?token=([\w-]+)/) || [])[1];
ok(Boolean(link), "and carries a link to this app's set-password page");
ok(inv.tokenHash !== link && !JSON.stringify(g.__invites).includes(link), "only the link's digest is kept, never the link");
ok(String(mail.html).startsWith("<p>Hi Sara Ali, you have been invited") && String(mail.html).includes(`<a href="https://app.test/set-password?token=${link}">`), "the process's own words come first, then the link as a link");

console.log("an address that already has a login");
const again = await invite({ ...step, email: "already@ditans.test", role: "DITANS Operations" }, ctx);
eqJson([again.invited, again.existing, again.userId], [false, true, "u-0"], "is told so");
eqJson(g.__users.find((u: any) => u.email === "already@ditans.test").accountType, "Candidate", "and that account's role is not changed");

console.log("a role the application does not declare");
const bad = await invite({ ...step, email: "x@ditans.test", role: "Admin" }, ctx);
ok(String(bad.error).includes("is not one of this application's roles"), "is refused");
ok(!g.__users.some((u: any) => u.email === "x@ditans.test"), "and no account is made");

console.log("no mail service");
g.__secrets = {};
const quiet = await invite({ ...step, email: "noor@ditans.test" }, ctx);
eqJson([quiet.invited, quiet.emailed], [true, false], "the account is still made");
ok(String(quiet.notice).includes("noor@ditans.test has an account now, but the email with their set-up link was not sent"), "and the run says the link did not go");
ok(!String(quiet.notice).includes("saved as a notification") && String(quiet.notice).endsWith("The link was not kept anywhere."), "without claiming it was kept");
ok(!JSON.stringify(g.__persisted).includes("set-password?token="), "and the link is not saved as a notification for anyone to read");

console.log("the test version, which emails only the organisation's own people");
g.__secrets = { SMTP_HOST: "smtp.test", SMTP_USER: "u", SMTP_PASS: "p" };
process.env.FORGE_ENVIRONMENT = "test"; process.env.FORGE_TEST_RECIPIENTS = "owner@forge.test";
const mailedBefore = g.__mailed.length;
const held = await invite({ ...step, email: "tester@outside.test" }, ctx);
eqJson([held.invited, held.emailed, g.__mailed.length - mailedBefore], [true, true, 1], "sends the invitation even to an outside address: held, the person could never set a password");
const other = await g.__handlers["send_email"]({ actionType: "send_email", to: "stranger@outside.test", subject: "Hello", body: "Hi" }, ctx);
ok(other.sent === false && String(other.notice).includes("This is the test version"), "while every other email to an outside address is still held");
delete process.env.FORGE_ENVIRONMENT; delete process.env.FORGE_TEST_RECIPIENTS;

done("a login for someone else is made by the process");
