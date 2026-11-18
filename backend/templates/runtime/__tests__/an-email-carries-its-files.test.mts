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
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "@/db/schema": "export const forgeNotifications = { __name: 'forge_notifications' };",
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'x'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = () => ({}); export const and = () => ({}); export const sql = (...a) => ({ __sql: a }); export const ne = (c, v) => ({ op: 'ne', col: c && c.__col, v }); export const gt = (c, v) => ({ op: 'gt', col: c && c.__col, v }); export const gte = (c, v) => ({ op: 'gte', col: c && c.__col, v }); export const lt = (c, v) => ({ op: 'lt', col: c && c.__col, v }); export const lte = (c, v) => ({ op: 'lte', col: c && c.__col, v }); export const inArray = (c, v) => ({ op: 'inArray', col: c && c.__col, v }); export const notInArray = (c, v) => ({ op: 'notInArray', col: c && c.__col, v });",
    "@/lib/error_reporter": "export const reportFromError = () => {};",
    "../fk-roles": "export const FK_ROLES = {}; export const fkRole = () => null; export const isDomainFk = () => false;",
    "@/lib/rules": "export const evaluateRuleSetForTable = async () => ({ errors: [], patches: {} });",
    "@/lib/storage": "export const loadFile = async (id) => id === 'f-invoice' ? { buffer: Buffer.from('%PDF-invoice'), contentType: 'application/pdf', filename: 'Mews invoice 30.pdf' } : id === 'f-receipt' ? { buffer: Buffer.from('%PDF-receipt'), contentType: 'application/pdf', filename: 'Mews receipt.pdf' } : null; export const saveFile = async () => ({ id: 'x' });",
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
const ctx: any = { input: { files: "f-invoice, f-receipt" }, variables: { files: "f-invoice, f-receipt" }, log: [] };
function reset(secrets: Record<string, string>, connected: Record<string, unknown>) {
  (globalThis as any).__secrets = secrets; (globalThis as any).__connected = connected;
  (globalThis as any).__persisted = []; (globalThis as any).__mailed = [];
}
const smtp = { send_email: { name: "Mail", provider: "smtp", keys: ["SMTP_HOST"], liveKey: "SMTP_HOST" } };

// ── an invoice and a receipt, named by id, go with the message (CARES, 18 Nov 2026) ──
reset({ SMTP_HOST: "smtp.test", FORGE_EMAIL_FROM: "desk@hotel.test" }, smtp);
let out: any = await send({ to: "guest@mail.test", subject: "Your case", body: "Resolved.", attachments: "{{files}}" }, ctx);
const mail = (globalThis as any).__mailed[0];
eqJson(out.sent, true, "the message is sent");
eqJson(out.attached, 2, "and says how many files went with it");
eqJson(mail?.attachments?.map((a: any) => a.filename), ["Mews invoice 30.pdf", "Mews receipt.pdf"], "both files ride on the mail, under their own names");
eqJson(mail?.attachments?.[0]?.content?.toString(), "%PDF-invoice", "with their own bytes");
eqJson(out.notice, undefined, "nothing to say when every file was read");

// ── a list works as well as a comma string; a file that is gone is left off and said ──
reset({ SMTP_HOST: "smtp.test", FORGE_EMAIL_FROM: "desk@hotel.test" }, smtp);
out = await send({ to: "guest@mail.test", subject: "s", body: "b", attachments: ["f-invoice", "gone", "f-invoice"] }, ctx);
eqJson((globalThis as any).__mailed[0]?.attachments?.length, 1, "the same file goes once; an unreadable one is left off");
ok(String(out.notice).includes("1 attachment could not be read"), "and the notice says one was left off");

// ── no attachments named: the message is exactly as before ──
reset({ SMTP_HOST: "smtp.test", FORGE_EMAIL_FROM: "desk@hotel.test" }, smtp);
out = await send({ to: "guest@mail.test", subject: "s", body: "b", attachments: "" }, ctx);
eqJson("attachments" in ((globalThis as any).__mailed[0] ?? {}), false, "no attachments key on a plain message");

// ── through Resend, the files go as base64 ──
reset({ RESEND_API_KEY: "re_x", FORGE_EMAIL_FROM: "desk@hotel.test" }, {});
let posted: any = null;
(globalThis as any).fetch = async (_u: string, init: any) => { posted = JSON.parse(init.body); return { ok: true, json: async () => ({ id: "re-1" }) }; };
out = await send({ to: "guest@mail.test", subject: "s", body: "b", attachments: "f-receipt" }, ctx);
eqJson(posted?.attachments, [{ filename: "Mews receipt.pdf", content: Buffer.from("%PDF-receipt").toString("base64") }], "Resend is given the file as base64");
eqJson(out.attached, 1, "one file went");
done("send_email attachments");
