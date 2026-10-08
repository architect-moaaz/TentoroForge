/**
 * The `mcp_tool_call` step finds its server, run from the SHIPPED
 * workflows/index.ts.
 *
 * SnapIT's Firecrawl steps named no server and failed "mcp_tool_call: no
 * server matched (id= name=)" (forge-v3, 2026-09-28). A step that names none
 * uses the app's only server, or the one its tool is named for; a name
 * written against the integration ("FireCrawl MCP") finds "Firecrawl".
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
(globalThis as any).__secrets = {};
(globalThis as any).__connected = {};
(globalThis as any).__persisted = [];
(globalThis as any).__mailed = [];
(globalThis as any).__called = [] as any[];

installHarness({
  stubs: {
    "@/db": "export const db = { insert: (t) => ({ values: async (v) => { globalThis.__persisted.push(v); return [v]; } }), execute: async () => ({ rows: [] }) };",
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "@/db/schema": "export const forgeNotifications = { __name: 'forge_notifications' };",
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'x'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = () => ({}); export const and = () => ({}); export const sql = (...a) => ({ __sql: a }); export const ne = (c, v) => ({ op: 'ne', col: c && c.__col, v }); export const gt = (c, v) => ({ op: 'gt', col: c && c.__col, v }); export const gte = (c, v) => ({ op: 'gte', col: c && c.__col, v }); export const lt = (c, v) => ({ op: 'lt', col: c && c.__col, v }); export const lte = (c, v) => ({ op: 'lte', col: c && c.__col, v }); export const inArray = (c, v) => ({ op: 'inArray', col: c && c.__col, v }); export const notInArray = (c, v) => ({ op: 'notInArray', col: c && c.__col, v });",
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
    "@/lib/integrations/mcpClientPool": "export const callMcpTool = async (server, tool, args) => { globalThis.__called.push({ server, tool, args }); return { ok: true }; };",
    fs: "export const promises = {}; export default { promises };",
    path: "export default { join: (...a) => a.join('/'), resolve: (...a) => a.join('/') }; export const join = (...a) => a.join('/');",
  },
});

const mod: any = await import("../workflows/index.ts");
mod.registerDefaultActions();
const call = (globalThis as any).__handlers.mcp_tool_call;
ok(typeof call === "function", "the shipped module registers an mcp_tool_call handler");

const ctx: any = { input: {}, variables: { query: "Nike Air Max 90" }, log: [] };
function servers(list: Record<string, string>) {
  for (const k of Object.keys(process.env)) if (k.startsWith("MCP_SERVER_")) delete process.env[k];
  for (const [slug, name] of Object.entries(list)) {
    process.env[`MCP_SERVER_${slug}_URL`] = `https://mcp.example/${slug}`;
    process.env[`MCP_SERVER_${slug}_NAME`] = name;
  }
  (globalThis as any).__called = [];
}
const last = () => (globalThis as any).__called.at(-1);

servers({ B2C2E135E8F2: "Firecrawl" });
let out = await call({ actionType: "mcp_tool_call", mcp_tool_name: "firecrawl_search", args: { query: "{{query}}" } }, ctx);
ok(!out.error, "no server named, one configured: it is the one");
eqJson(last()?.server, "B2C2E135E8F2", "called on the app's only server");

servers({ AAAAAAAAAAAA: "Bright Data", B2C2E135E8F2: "Firecrawl" });
out = await call({ actionType: "mcp_tool_call", mcp_tool_name: "firecrawl_search", args: { query: "x" } }, ctx);
eqJson(last()?.server, "B2C2E135E8F2", "no server named, several: the one the tool is named for");

out = await call({ actionType: "mcp_tool_call", mcp_server_name: "FireCrawl MCP", mcp_tool_name: "firecrawl_search", args: { query: "x" } }, ctx);
eqJson(last()?.server, "B2C2E135E8F2", "a name written against the integration finds the server");

(globalThis as any).__called = [];
out = await call({ actionType: "mcp_tool_call", mcp_server_name: "Apify", mcp_tool_name: "firecrawl_search", args: {} }, ctx);
ok(String(out.error).includes("no server matched"), "a name that matches nothing still says so");
eqJson((globalThis as any).__called.length, 0, "and calls nothing");

servers({});
out = await call({ actionType: "mcp_tool_call", mcp_tool_name: "firecrawl_search", args: {} }, ctx);
ok(String(out.error).includes("no server matched"), "an app with no server says so");

done("mcp_tool_call finds its server");
