/**
 * A call the process can do without is skipped when its service is not
 * connected.
 *
 * DITANS's Send Offer asks DocuSign for an e-signature; on Test, where no
 * DocuSign key is set, "DOCUSIGN_API_KEY is not set in this environment"
 * stopped every offer (2026-11-19). A step that says what the person is told
 * instead (`ifNotConnected`) is skipped, the run goes on, and the sentence
 * comes back as the run's notice. A step that says nothing still fails.
 *
 * Runs the SHIPPED workflows/index.ts http_call handler.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
(globalThis as any).__secrets = {};
(globalThis as any).__connected = {};
(globalThis as any).__persisted = [] as any[];
(globalThis as any).__mailed = [];

installHarness({
  stubs: {
    "@/db": "export const db = { insert: (t) => ({ values: (v) => { globalThis.__persisted.push(v); const r = Promise.resolve([v]); r.returning = async () => [{ ...v, id: 'n-1' }]; return r; } }), execute: async () => ({ rows: [] }) };",
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "@/db/schema": "export const forgeNotifications = (globalThis.__ntf = { __name: 'forge_notifications' });",
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'x'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = () => ({}); export const and = (...p) => ({ op: 'and', parts: p }); export const sql = (...a) => ({ __sql: a }); export const ne = (c, v) => ({ op: 'ne', col: c && c.__col, v }); export const gt = (c, v) => ({ op: 'gt', col: c && c.__col, v }); export const gte = (c, v) => ({ op: 'gte', col: c && c.__col, v }); export const lt = (c, v) => ({ op: 'lt', col: c && c.__col, v }); export const lte = (c, v) => ({ op: 'lte', col: c && c.__col, v }); export const inArray = (c, v) => ({ op: 'inArray', col: c && c.__col, v }); export const notInArray = (c, v) => ({ op: 'notInArray', col: c && c.__col, v });",
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
const call = (globalThis as any).__handlers["http_call"];
ok(typeof call === "function", "http_call is registered");

const sent: any[] = [];
(globalThis as any).fetch = async (url: string, init: any) => {
  sent.push({ url, ...init });
  return new Response(JSON.stringify({ envelopeId: "env-1" }), { status: 201, headers: { "content-type": "application/json" } });
};
const ctx: any = { input: {}, variables: { offer: { jobTitle: "Staff Nurse — ICU" } }, log: [] };
const esign = { actionType: "http_call", url: "https://api.docusign.net/restapi/v2.1/accounts/envelopes", method: "POST",
                auth: { secretRef: "DOCUSIGN_API_KEY" } };
delete process.env.DOCUSIGN_API_KEY;

console.log("a call the process cannot do without");
const failed = await call(esign, ctx);
eqJson(failed.error, "DOCUSIGN_API_KEY is not set in this environment", "still fails the step, as before");

console.log("a call the process can do without");
const skipped = await call({ ...esign, ifNotConnected: "DocuSign is not connected, so the offer for {{offer.jobTitle}} went without an e-signature request." }, ctx);
ok(!("error" in skipped), "is not an error: the run goes on");
eqJson([skipped.skipped, skipped.connected, skipped.ok], [true, false, false], "its output says it was skipped, so a later step can record that");
eqJson(skipped.notice, "DocuSign is not connected, so the offer for Staff Nurse — ICU went without an e-signature request.",
       "and the sentence, templates resolved, is the notice the person is shown");
eqJson(sent.length, 0, "nothing is called");

console.log("once the service is connected");
process.env.DOCUSIGN_API_KEY = "ds-key";
const made = await call({ ...esign, ifNotConnected: "not connected" }, ctx);
eqJson([made.ok, made.status, made.skipped, made.notice], [true, 201, undefined, undefined], "the call is made and says nothing of being skipped");
eqJson(sent[0].headers["Authorization"], "Bearer ds-key", "signed as before");
ok(!JSON.stringify(ctx.variables).includes("ds-key"), "the key never enters the run's variables");
delete process.env.DOCUSIGN_API_KEY;

done("a call the process can do without is skipped when its service is not connected");
