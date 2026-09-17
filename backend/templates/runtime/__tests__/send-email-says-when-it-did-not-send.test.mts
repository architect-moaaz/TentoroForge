/**
 * The `send_email` step, run from the SHIPPED workflows/index.ts.
 *
 * It used to return `{sent: true, channel: "in_app"}` whenever there was no
 * provider to send through — so an owner watched "Register Nurse complete ·
 * 3 steps" while the nurse got nothing, and no screen anywhere said why.
 * Four outcomes, and each one has to say which it is:
 *
 *   1. the declared service is connected      -> sent, through that provider
 *   2. declared, credential not set here      -> not sent, and it says so
 *   3. nothing declared at all                -> not sent, and it says so
 *   4. sent, but from nobody's address        -> sent, with the address said
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";

// The secrets this run "has", by name. Rewritten per case — the resolver stub
// reads it at call time, exactly as getSecret reads process.env.
(globalThis as any).__secrets = {} as Record<string, string>;
// What the declared connection is. Empty means the projection wrote no entry
// for send_email, which is an application with no email service connected.
(globalThis as any).__connected = {} as Record<string, unknown>;
// Every row the fallback persisted, so "the message is not lost" is checked
// rather than asserted in a comment.
(globalThis as any).__persisted = [] as unknown[];
// The mail the SMTP transport was asked to send.
(globalThis as any).__mailed = [] as any[];

installHarness({
  stubs: {
    "@/db": "export const db = { insert: (t) => ({ values: async (v) => { globalThis.__persisted.push(v); return [v]; } }), execute: async () => ({ rows: [] }) };",
    "@/db/schema": "export const forgeNotifications = { __name: 'forge_notifications' };",
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'x'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = () => ({}); export const and = () => ({}); export const sql = (...a) => ({ __sql: a });",
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
const send = (globalThis as any).__handlers.send_email;
ok(typeof send === "function", "the shipped module registers a send_email handler");

const ctx: any = { input: {}, variables: {}, log: [] };
const config = { to: "nurse@ward.test", subject: "Welcome", body: "You are registered." };

function reset(secrets: Record<string, string>, connected: Record<string, unknown>) {
  (globalThis as any).__secrets = secrets;
  (globalThis as any).__connected = connected;
  (globalThis as any).__persisted = [];
  (globalThis as any).__mailed = [];
}

const outlook = {
  send_email: {
    name: "Microsoft 365 / Outlook", provider: "smtp",
    keys: ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "FORGE_EMAIL_FROM"],
    liveKey: "SMTP_HOST", fromKey: "FORGE_EMAIL_FROM",
  },
};

// ── 1. connected ───────────────────────────────────────────────────────────
reset({ SMTP_HOST: "smtp.office365.com", SMTP_USER: "u", SMTP_PASSWORD: "p",
        FORGE_EMAIL_FROM: "clinic@ward.test" }, outlook);
let out: any = await send(config, ctx);
eqJson(out.sent, true, "a connected service sends");
eqJson(out.channel, "smtp", "through the provider the owner chose");
eqJson(out.notice, undefined, "and says nothing, because nothing needs saying");
eqJson((globalThis as any).__mailed[0]?.from, "clinic@ward.test",
       "from the address the owner set");
eqJson((globalThis as any).__persisted.length, 0, "no fallback notification");

// ── 2. declared, credential not set in THIS environment ───────────────────
reset({}, outlook);
out = await send(config, ctx);
eqJson(out.sent, false, "a declaration with no credential does not claim a send");
ok(String(out.notice).includes("Microsoft 365 / Outlook"),
   "the notice names the service the owner chose");
ok(String(out.notice).includes("SMTP_HOST"),
   "and the variable that is missing, which is a name and not a secret");
eqJson((globalThis as any).__persisted.length, 1,
       "the message is kept, so nothing is lost");

// ── 3. nothing connected at all ────────────────────────────────────────────
reset({}, {});
out = await send(config, ctx);
eqJson(out.sent, false, "no service connected: not sent");
ok(String(out.notice).includes("No email service is connected"),
   "the notice says so in the words an owner would use");
ok(String(out.notice).includes("saved as a notification"),
   "and says where the message went instead");

// ── 4. sent, but from the stand-in address ─────────────────────────────────
reset({ SMTP_HOST: "smtp.office365.com" }, outlook);
out = await send(config, ctx);
eqJson(out.sent, true, "a send with no from-address still goes");
ok(String(out.notice).includes("FORGE_EMAIL_FROM"),
   "but the weird address is called out, not left for a customer to notice");

// ── a declared provider is not rescued by the other one's stray key ───────
reset({ RESEND_API_KEY: "re_xxx" }, outlook);
out = await send(config, ctx);
eqJson(out.sent, false,
       "an SMTP declaration does not silently send through Resend");
ok(String(out.notice).includes("SMTP_HOST"), "it says which credential it wanted");

// ── no declaration, but the environment holds a key: unchanged behaviour ──
reset({ RESEND_API_KEY: "re_xxx" }, {});
(globalThis as any).fetch = async () => ({ ok: true, json: async () => ({ id: "re-1" }) });
out = await send(config, ctx);
eqJson(out.sent, true, "an app built before connections existed keeps sending");
eqJson(out.channel, "email", "through the key its environment holds");

// ── the run carries the notices ────────────────────────────────────────────
const engine: any = await import("../workflows/engine.ts");
eqJson(
  engine.noticesOf([
    { output: { sent: true } },
    { output: { notice: "No email service is connected to this application." } },
    { output: { notice: "No email service is connected to this application." } },
  ]),
  ["No email service is connected to this application."],
  "every step's notice reaches the run, once per distinct thing to fix",
);
eqJson(engine.noticesOf([]), [], "a clean run carries none");

done("send_email honesty");
