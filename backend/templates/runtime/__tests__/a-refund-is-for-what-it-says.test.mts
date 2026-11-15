/**
 * The `refund_payment` step, run from the SHIPPED workflows/index.ts.
 *
 * Every gateway reads a refund with no amount as "refund it all". A step that
 * names an amount and resolves none (a field the form did not send, a zero,
 * some text) used to send no amount — a full refund for a part. It refuses
 * now; a part never goes past what is left; and the same refund asked twice
 * carries one idempotency key, so the gateway makes it once.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
(globalThis as any).__secrets = {};
(globalThis as any).__connected = {};
(globalThis as any).__persisted = [];
(globalThis as any).__mailed = [];

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
    fs: "export const promises = {}; export default { promises };",
    "../payments": "export const ledgerGet = async (id) => (globalThis.__row && globalThis.__row.id === id ? globalThis.__row : null); export const secretsFor = async () => ({ secret: 'sk_test_x' }); export const toMinor = (a) => Math.round(a * 100); export const toMajor = (m) => m / 100; export const gateways = () => [{ provider: 'stripe', integration: 'stripe' }]; export const ledgerSet = async (id, p) => { globalThis.__sets.push(p); }; export const settle = async (slug, ev) => { globalThis.__settled.push(ev); return { moved: true }; }; export const ADAPTERS = { stripe: { refund: async (input) => { globalThis.__refunds.push(input); return { refundId: 're_' + globalThis.__refunds.length, status: 'succeeded' }; } } };",
    path: "export default { join: (...a) => a.join('/'), resolve: (...a) => a.join('/') }; export const join = (...a) => a.join('/');",
  },
});

const mod: any = await import("../workflows/index.ts");
mod.registerDefaultActions();
const refund = (globalThis as any).__handlers.refund_payment;
ok(typeof refund === "function", "the shipped module registers a refund_payment handler");

function reset(refundedMinor = 0) {
  (globalThis as any).__row = { id: "p-1", provider: "stripe", provider_ref: "cs_1", status: "succeeded", amount_minor: 10000,
    currency: "USD", metadata: refundedMinor ? { refundedMinor } : {} };
  (globalThis as any).__refunds = [];
  (globalThis as any).__sets = [];
  (globalThis as any).__settled = [];
}
const ctx = (input: Record<string, unknown>) => ({ input, variables: { ...input }, log: [] }) as any;

for (const [what, amount] of [["a field the form did not send", "{{input.refundAmount}}"], ["zero", 0], ["text", "half"]] as const) {
  reset();
  const out = await refund({ paymentId: "p-1", amount }, ctx({ refundAmount: amount === 0 ? 0 : undefined }));
  ok(out?.error && (globalThis as any).__refunds.length === 0, `an amount that is ${what} refuses, and nothing is refunded (not all of it)`);
}

reset();
let out = await refund({ paymentId: "p-1", amount: 40 }, ctx({}));
const first = (globalThis as any).__refunds[0];
ok(!out.error && first?.amountMinor === 4000, "a part is refunded as that part");
eqJson((globalThis as any).__sets.at(-1), { metadata: { refundedMinor: 4000 } }, "and what was refunded so far is written down");
ok((globalThis as any).__settled.at(-1)?.amountMinor === 4000 && (globalThis as any).__settled.at(-1)?.metadata?.refundId === "re_1",
  "the ledger hears this refund, under the gateway's refund id");

reset(4000);
out = await refund({ paymentId: "p-1", amount: 70 }, ctx({}));
ok(out?.error && /only 60/.test(out.error) && (globalThis as any).__refunds.length === 0, "a part past what is left is refused, and says how much is left");
out = await refund({ paymentId: "p-1", amount: 60 }, ctx({}));
ok(!out.error && (globalThis as any).__settled.at(-1)?.amountMinor === 6000 && (globalThis as any).__sets.at(-1)?.metadata?.refundedMinor === 10000,
  "the rest refunded: the whole is written down as refunded");

reset(4000);
await refund({ paymentId: "p-1" }, ctx({}));
ok((globalThis as any).__refunds[0]?.amountMinor === undefined && (globalThis as any).__settled.at(-1)?.amountMinor === 6000,
  "no amount named is the rest of it");

reset(10000);
out = await refund({ paymentId: "p-1" }, ctx({}));
ok(out?.error && (globalThis as any).__refunds.length === 0, "a payment refunded in full already is not refunded again");

reset();
await refund({ paymentId: "p-1", amount: 25 }, ctx({}));
await refund({ paymentId: "p-1", amount: 25 }, ctx({}));
const keys = (globalThis as any).__refunds.map((r: any) => r.idempotencyKey);
ok(keys[0] && keys[0] === keys[1], "the same refund asked twice (a retried step) carries one key: the gateway makes it once");
done("a refund is for what it says");
