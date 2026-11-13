/**
 * A PayPal payment in a currency PayPal takes in whole units is paid when it
 * is paid.
 *
 * #37 review, 2026-11-13: PayPal takes HUF, JPY and TWD with no decimals. A
 * 1234.56 HUF order was sent as "1235", PayPal reported 1235 back, and the
 * ledger's 123456 against the event's 123500 was called a mismatch. The
 * payment was marked failed after the payer had been charged. The check now
 * compares the amounts as PayPal was sent them. Any other gateway, and a real
 * difference at PayPal, is still refused.
 *
 * Runs the SHIPPED payments/index.ts and paypal.ts over a stand-in database.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness({
  stubs: {
    "drizzle-orm": "export const sql = Object.assign((s, ...v) => ({ text: s.join('?'), v }), { join: (xs) => ({ text: '', v: xs }) });",
    "@/db": `export const db = { execute: async (q) => {
      const t = q.text; const g = globalThis;
      if (t.startsWith('SELECT')) return { rows: g.__row ? [g.__row] : [] };
      if (t.includes('SET status') && t.includes('RETURNING')) { g.__moved.push(q.v[0]); g.__row.status = q.v[0]; return { rows: [{ id: g.__row.id }] }; }
      if (t.includes('SET metadata')) { g.__meta.push(JSON.parse(q.v[0])); return { rows: [] }; }
      return { rows: [] };
    } };`,
    "@/lib/integrations/connected": "export const connectedService = () => null;",
    "@/lib/integrations/resolver": "export const getSecret = async () => null;",
    "@/lib/payments-config": "export const PAYMENTS = { needed: true, currency: 'HUF', models: ['one_time'], access: 'none', gateways: [], plans: [] };",
    "@/lib/events/bus": "export const emitEventAndProcess = async () => ({});",
  },
});
const { settle } = await import("../payments/index.ts");
const g = globalThis as any;

async function pay(provider: string, currency: string, ledgerMinor: number, reportedMinor: number) {
  g.__row = { id: "11111111-1111-1111-1111-111111111111", provider, provider_ref: "ORDER-1", status: "pending",
              amount_minor: ledgerMinor, currency, metadata: {} };
  g.__moved = []; g.__meta = [];
  await settle(provider, { type: "payment.succeeded", providerRef: "ORDER-1", amountMinor: reportedMinor, currency, metadata: {} });
  return { moved: g.__moved.at(-1), mismatch: g.__meta.find((m: any) => m.mismatch)?.mismatch };
}

let r = await pay("paypal", "HUF", 123456, 123500);
eqJson(r, { moved: "succeeded", mismatch: undefined }, "1234.56 HUF sent as 1235 and reported 1235 is paid");
r = await pay("paypal", "JPY", 1200, 1200);
eqJson(r.moved, "succeeded", "JPY as before");
r = await pay("paypal", "HUF", 123456, 120000);
eqJson(r.moved, "failed", "a real difference at PayPal is still refused");
ok(Boolean(r.mismatch), "and recorded");
r = await pay("paypal", "USD", 1250, 1251);
eqJson(r.moved, "failed", "a cent off in USD is refused");
r = await pay("stripe", "HUF", 123456, 123500);
eqJson(r.moved, "failed", "Stripe is held to the ledger's exact amount");

done("whole-unit-paypal");
