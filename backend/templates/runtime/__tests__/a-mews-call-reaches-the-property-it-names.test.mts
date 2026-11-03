/**
 * A Mews call reaches the property it names, with that property's own token —
 * opened inside the call and nowhere else — and only the application's
 * administrator manages the properties.
 *
 * An application serving many hotels keeps each one's access token sealed in
 * `forge_mews_properties`; a step says which hotel (`auth.property`), and the
 * SHIPPED http_call handler and `src/lib/mews.ts` sign the call. A property
 * without a token of its own is reached with the organisation's portfolio
 * token and its enterprise id. The routes answer 401 / 404 / 403 before any
 * property is read. The database is a stand-in: the SQL itself is proven
 * against Postgres separately.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { webcrypto } from "node:crypto";

const noop = "export default {}; export const __noop = true;";
const g: any = globalThis;
g.__props = [] as any[];
g.__declared = { "mews-pms": { name: "Mews PMS", provider: "mews", keys: ["MEWS_CLIENT_TOKEN"] } };
g.__session = null;
g.__dbCalls = 0;

// The stand-in database: the statements src/lib/mews.ts runs, recognised by
// their text, answered from `__props`.
const sqlText = (q: any): { text: string; values: any[] } => {
  const values: any[] = [];
  const walk = (node: any): string => {
    if (!node || !node.__sql) { values.push(node); return "$"; }
    const [strings, ...vals] = node.__sql;
    return strings.map((s: string, i: number) => s + (i < vals.length ? walk(vals[i]) : "")).join("");
  };
  return { text: walk(q).replace(/\s+/g, " "), values };
};
g.__execute = async (q: any) => {
  g.__dbCalls++;
  const { text, values } = sqlText(q);
  if (text.startsWith(" CREATE TABLE") || text.startsWith("CREATE TABLE")) return { rows: [] };
  if (text.includes("LIMIT 2")) return { rows: g.__props.slice(0, 2) };
  if (text.includes("ORDER BY lower(name)")) {
    return { rows: g.__props.map((p: any) => ({ ...p, has_token: Boolean(p.access_token_encrypted), access_token_encrypted: undefined })) };
  }
  if (text.includes("lower(name) = lower(") && text.includes("ORDER BY")) {
    const key = String(values.find((v) => typeof v === "string") ?? "").toLowerCase();
    const row = g.__props.find((p: any) => p.id === key || p.enterprise_id === key || p.name.toLowerCase() === key);
    return { rows: row ? [row] : [] };
  }
  throw new Error(`unexpected statement: ${text}`);
};

installHarness({
  stubs: {
    "@/db": "export const db = { insert: () => ({ values: async () => [] }), execute: (q) => globalThis.__execute(q) };",
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "@/db/schema": "export const forgeNotifications = { __name: 'forge_notifications' };",
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'x'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = () => ({}); export const and = (...p) => ({ op: 'and', parts: p }); export const sql = (...a) => ({ __sql: a }); export const ne = () => ({}); export const gt = () => ({}); export const gte = () => ({}); export const lt = () => ({}); export const lte = () => ({}); export const inArray = () => ({}); export const notInArray = () => ({});",
    "@/lib/error_reporter": "export const reportFromError = () => {};",
    "../fk-roles": "export const FK_ROLES = {}; export const fkRole = () => null; export const isDomainFk = () => false;",
    "@/lib/rules": "export const evaluateRuleSetForTable = async () => ({ errors: [], patches: {} });",
    "@/lib/integrations/resolver": "export const getSecret = async () => undefined; export const clearSecretCache = () => {};",
    "@/lib/integrations/connected": "export const connectedService = () => undefined; export const CONNECTED_SERVICES = {}; export const DECLARED = globalThis.__declared;",
    nodemailer: "export const createTransport = () => ({ sendMail: async () => ({}) }); export default { createTransport };",
    "./engine": "globalThis.__handlers = {}; export const getActionHandler = (n) => globalThis.__handlers[n]; export const registerActionHandler = (n, h) => { globalThis.__handlers[n] = h; }; export const registerStepHandler = () => {}; export const executeWorkflow = async () => ({}); export const WorkflowEngine = class {}; export const getEngine = () => ({}); export const registerTriggerHandler = () => {}; export const runWorkflow = async () => ({});",
    "./ai": "export const registerAIActions = () => {};",
    "./ocr": "export const registerOcrActions = () => {};",
    "../events/emit-node": "export const makeEmitEventHandler = () => async () => ({});",
    "../feel-lite": "export const evaluateExpression = () => null;",
    "./types": noop,
    fs: "export const promises = {}; export default { promises };",
    path: "export default { join: (...a) => a.join('/'), resolve: (...a) => a.join('/') }; export const join = (...a) => a.join('/');",
    "@/auth": "export const auth = async () => globalThis.__session;",
    "@/lib/account": "export const ADMIN_ROLE = 'Manager';",
    "@/lib/tenancy": "export const isPlatformRole = (r) => r === 'platform_admin';",
  },
  redirect: { "@/lib/mews": new URL("../mews.ts", import.meta.url).pathname },
});

process.env.SENSITIVE_ENCRYPTION_KEY = Buffer.from(webcrypto.getRandomValues(new Uint8Array(32))).toString("base64");
const crypto: any = await import("../sensitive-crypto.ts");
const seal = (t: string) => crypto.encryptSensitive(t);

const mod: any = await import("../workflows/index.ts");
mod.registerDefaultActions();
const call = g.__handlers["http_call"];

const sent: any[] = [];
g.fetch = async (url: string, init: any) => {
  sent.push({ url, ...init, json: init.body ? JSON.parse(init.body) : null });
  return new Response(JSON.stringify({ Reservations: [] }), { status: 200, headers: { "content-type": "application/json" } });
};

const LISBON = { id: "0b5c7b0e-1111-4c4a-8e01-a4fc46b25178", name: "Lisbon Riverside", enterprise_id: "851df8c8-90f2-4c4a-8e01-a4fc46b25178",
                 environment: "production", access_token_encrypted: await seal("at-lisbon-secret") };
const PORTO = { id: "0b5c7b0e-2222-4c4a-8e01-a4fc46b25178", name: "Porto Old Town", enterprise_id: "aa5c7b0e-2222-4c4a-8e01-a4fc46b25178",
                environment: "demo", access_token_encrypted: null };
g.__props = [LISBON, PORTO];

process.env.MEWS_CLIENT_TOKEN = "ct-integration";
delete process.env.MEWS_ACCESS_TOKEN;
delete process.env.MEWS_ENVIRONMENT;
const ctx: any = { input: {}, variables: { hotel: LISBON.id, place: "porto old town" }, log: [] };
const step = (auth: any) => ({ actionType: "http_call", url: "/api/connector/v1/reservations/getAll/2023-06-06",
                               auth, body: { Limitation: { Count: 10 } } });

// ── A named property, its own token ────────────────────────────────────────
const lisbon = await call(step({ provider: "mews", property: "{{hotel}}" }), ctx);
ok(lisbon.ok === true, "a call to a named property goes through");
eqJson(sent[0].url, "https://api.mews.com/api/connector/v1/reservations/getAll/2023-06-06", "on the property's own environment (production)");
eqJson([sent[0].json.ClientToken, sent[0].json.AccessToken], ["ct-integration", "at-lisbon-secret"],
       "signed with the organisation's client token and the property's own access token, opened from its seal");
eqJson(sent[0].json.EnterpriseId, LISBON.enterprise_id, "and its enterprise id");
ok(!JSON.stringify(ctx.variables).includes("at-lisbon-secret") && !JSON.stringify(lisbon).includes("at-lisbon-secret"),
   "the token reaches neither the run's variables nor the step's output");
ok(!String(LISBON.access_token_encrypted).includes("at-lisbon-secret"), "what is stored is the seal, not the token");

// ── By name, no token of its own: the portfolio token ──────────────────────
const noPortfolio = await call(step({ provider: "mews", property: "{{place}}" }), ctx);
ok(String(noPortfolio.error).includes('"Porto Old Town" has no access token, and MEWS_ACCESS_TOKEN (the portfolio token) is not set'),
   "a property with no token, and no portfolio token, says so");
process.env.MEWS_ACCESS_TOKEN = "at-portfolio";
await call(step({ provider: "mews", property: "{{place}}" }), ctx);
const porto = sent[sent.length - 1];
eqJson(porto.url, "https://api.mews-demo.com/api/connector/v1/reservations/getAll/2023-06-06", "found by its name, on its environment (demo)");
eqJson([porto.json.AccessToken, porto.json.EnterpriseId], ["at-portfolio", PORTO.enterprise_id],
       "reached with the portfolio token and its enterprise id");

// ── A property nobody chose is never called ────────────────────────────────
const before = sent.length;
const missing = await call(step({ provider: "mews", property: "Madrid" }), ctx);
ok(String(missing.error).includes('No Mews property is "Madrid"'), "a named property that is not there is an error");
ok(sent.length === before, "and nothing is sent");
await call(step({ provider: "mews", property: "{{nothing}}" }), ctx);
const fallback = sent[sent.length - 1];
eqJson(fallback.json.AccessToken, "at-portfolio", "a property left out uses the organisation's own token when it set one");
ok(fallback.json.EnterpriseId === undefined, "with no enterprise id of a property it did not name");
delete process.env.MEWS_ACCESS_TOKEN;
const several = await call(step({ provider: "mews" }), ctx);
ok(String(several.error).includes("several Mews properties: the step must say which"), "several properties and none named is an error");
g.__props = [LISBON];
await call(step({ provider: "mews" }), ctx);
eqJson(sent[sent.length - 1].json.AccessToken, "at-lisbon-secret", "with only one property, a step need not name it");
const given = await call({ ...step({ provider: "mews", property: LISBON.enterprise_id }), body: { EnterpriseId: "kept-as-given" } }, ctx);
ok(given.ok && sent[sent.length - 1].json.EnterpriseId === "kept-as-given", "an enterprise id the step writes itself is kept");

// ── Only the administrator manages properties ──────────────────────────────
const route: any = await import("../api-mews/properties/route.ts");
g.__dbCalls = 0;
g.__session = null;
eqJson((await route.GET()).status, 401, "signed out: 401");
g.__session = { user: { id: "u-1", role: "Receptionist" } };
eqJson((await route.GET()).status, 403, "anyone but the administrator: 403");
const post = await route.POST(new Request("http://app/api/mews/properties", { method: "POST", body: JSON.stringify({ name: "x", accessToken: "y" }) }));
eqJson(post.status, 403, "and cannot add one");
eqJson(g.__dbCalls, 0, "no property is read or written for them");
const keep = g.__declared["mews-pms"];
delete g.__declared["mews-pms"];
g.__session = { user: { id: "u-2", role: "Manager" } };
eqJson((await route.GET()).status, 404, "an application with no Mews integration: 404");
g.__declared["mews-pms"] = keep;
g.__session = { user: { id: "u-3", role: "platform_admin" } };
const platform = await route.GET();
eqJson(platform.status, 200, "the platform's own roles are let in");
const listed = await platform.json();
eqJson(listed.properties.map((p: any) => [p.name, p.hasToken]), [["Lisbon Riverside", true]], "the list says which property has its own token");
ok(!JSON.stringify(listed).includes(String(LISBON.access_token_encrypted)) && !JSON.stringify(listed).includes("at-lisbon-secret"),
   "and carries neither the token nor its seal");

done("a Mews call reaches the property it names");
