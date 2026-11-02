/**
 * A step reaches Mews the way Mews reads a call: a POST to the demo or live
 * host, the two tokens and the client name in the JSON body. Its Connector API
 * takes no header, so the generic `auth: {secretRef}` (bearer, header, basic,
 * query) could not sign it; the step says `auth: {provider: "mews"}` and the
 * path, and the SHIPPED http_call handler adds the rest from the environment.
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
  return new Response(JSON.stringify({ Reservations: [] }), { status: 200, headers: { "content-type": "application/json" } });
};
const ctx: any = { input: {}, variables: { since: "2026-11-01T00:00:00Z" }, log: [] };
const step = { actionType: "http_call", url: "/api/connector/v1/reservations/getAll/2023-06-06", method: "GET",
               auth: { provider: "mews" }, body: { CreatedUtc: { StartUtc: "{{since}}" }, Limitation: { Count: 10 } } };

delete process.env.MEWS_CLIENT_TOKEN; delete process.env.MEWS_ACCESS_TOKEN;
const unset = await call(step, ctx);
ok(String(unset.error).includes("MEWS_CLIENT_TOKEN and MEWS_ACCESS_TOKEN are not set"), "without the tokens it says which are missing");
eqJson(sent.length, 0, "and calls nothing");

process.env.MEWS_CLIENT_TOKEN = "ct-demo"; process.env.MEWS_ACCESS_TOKEN = "at-demo";
const demo = await call(step, ctx);
eqJson(sent[0].url, "https://api.mews-demo.com/api/connector/v1/reservations/getAll/2023-06-06", "the demo host when no environment is chosen");
eqJson(sent[0].method, "POST", "every Mews call is a POST");
const body = JSON.parse(sent[0].body);
eqJson([body.ClientToken, body.AccessToken, body.Client], ["ct-demo", "at-demo", "Tentoro Forge 1.0.0"], "the tokens and client name ride in the body");
eqJson(body.CreatedUtc, { StartUtc: "2026-11-01T00:00:00Z" }, "the operation's own fields are kept, templates resolved");
ok(!("Authorization" in sent[0].headers), "no header carries a token");
ok(demo.ok === true && Array.isArray(demo.body.Reservations), "the answer comes back as the step's output");
ok(!JSON.stringify(ctx.variables).includes("at-demo"), "the token never enters the run's variables");

process.env.MEWS_ENVIRONMENT = "production"; process.env.MEWS_CLIENT = "Case Desk 2.1";
await call(step, ctx);
eqJson(sent[1].url, "https://api.mews.com/api/connector/v1/reservations/getAll/2023-06-06", "the live host in production");
eqJson(JSON.parse(sent[1].body).Client, "Case Desk 2.1", "the client name the organisation set");

await call({ ...step, auth: { secretRef: "MEWS_ACCESS_TOKEN" }, url: "https://example.test/x" }, ctx);
eqJson(sent[2].headers["Authorization"], "Bearer at-demo", "a step that names a secret is signed as before");
// A step written before the adapter calls the live host with a bearer token;
// Mews would refuse it. It is signed in the body, on the chosen environment.
process.env.MEWS_ENVIRONMENT = "demo";
await call({ actionType: "http_call", url: "https://api.mews.com/api/connector/v1/payments/getAll", method: "POST",
             auth: { secretRef: "MEWS_ACCESS_TOKEN" }, body: { Limitation: { Count: 5 } } }, ctx);
eqJson(sent[3].url, "https://api.mews-demo.com/api/connector/v1/payments/getAll", "an old step to a Mews host goes to the chosen environment");
eqJson(JSON.parse(sent[3].body).AccessToken, "at-demo", "signed in the body");
ok(!("Authorization" in sent[3].headers), "not as a bearer Mews would refuse");
await call({ ...step, url: "https://api.mews.com.evil.test/x", auth: undefined }, ctx);
ok(!String(sent[4].body).includes("at-demo"), "a host that only starts like Mews's gets no token");
done("a step reaches Mews the way Mews reads it");
