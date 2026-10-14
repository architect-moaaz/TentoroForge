/**
 * The Stripe adapter believes a call only when `Stripe-Signature` checks
 * out, reads the provider's events into the application's own vocabulary,
 * converts major to minor units per currency, and the stand-in sends the
 * person to the application's own page. Runs the SHIPPED payments modules.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import crypto from "node:crypto";

installHarness({ stubs: {
  "drizzle-orm": "export const sql = (s, ...v) => ({ s, v });",
  "@/db": "export const db = { async execute() { return []; } };",
  "@/lib/integrations/connected": "export function connectedService() { return undefined; }",
  "@/lib/integrations/resolver": "export async function getSecret() { return ''; }",
} });

const { stripeAdapter }: any = await import("../payments/stripe.ts");
const pay: any = await import("../payments/index.ts");

const raw = JSON.stringify({ id: "evt_1", type: "checkout.session.completed", data: { object: { id: "cs_1", payment_status: "paid",
  amount_total: 1250, currency: "aed", metadata: { paymentId: "p-1", entity: "Order", entityId: "o-1" } } } });
const sign = (secret: string, t = Math.floor(Date.now() / 1000)) =>
  `t=${t},v1=${crypto.createHmac("sha256", secret).update(`${t}.${raw}`).digest("hex")}`;
{
  const good = stripeAdapter.verifyWebhook(raw, new Headers({ "stripe-signature": sign("whsec_x") }), "whsec_x");
  ok(good.ok && good.eventId === "evt_1", "a signed call is believed and carries the event id");
  ok(!stripeAdapter.verifyWebhook(raw, new Headers({ "stripe-signature": sign("other") }), "whsec_x").ok, "a forged one is not");
  const stale = stripeAdapter.verifyWebhook(raw, new Headers({ "stripe-signature": sign("whsec_x", Math.floor(Date.now() / 1000) - 3600) }), "whsec_x");
  eqJson(stale, { ok: false, reason: "stale signature" }, "an hour-old one is stale");
  ok(!stripeAdapter.verifyWebhook(raw, new Headers(), "whsec_x").ok, "none is refused");
}
{
  const ev = stripeAdapter.normalizeEvent(JSON.parse(raw));
  eqJson({ type: ev.type, providerRef: ev.providerRef, paymentId: ev.paymentId, amountMinor: ev.amountMinor, currency: ev.currency },
         { type: "payment.succeeded", providerRef: "cs_1", paymentId: "p-1", amountMinor: 1250, currency: "AED" }, "the provider's event in the app's words");
  eqJson(stripeAdapter.normalizeEvent({ type: "charge.refunded", data: { object: { id: "ch_1", payment_intent: "pi_1", amount_refunded: 500, currency: "aed", metadata: {} } } }).type,
         "refund.succeeded", "a refund");
  eqJson(stripeAdapter.normalizeEvent({ type: "customer.created", data: { object: {} } }), null, "an event the app has no word for is ignored");
  eqJson(stripeAdapter.normalizeEvent({ type: "checkout.session.completed", data: { object: { id: "cs_2", payment_status: "unpaid", metadata: {} } } }), null, "completed but unpaid is not paid");
}
{
  eqJson(pay.toMinor(12.5, "AED"), 1250, "major to minor");
  eqJson(pay.toMinor(1250, "JPY"), 1250, "a zero-decimal currency has no minor");
  eqJson(pay.toMajor(1250, "GBP"), 12.5, "and back");
}
{
  const { standInAdapter }: any = await import("../payments/stand-in.ts");
  const out = await standInAdapter.createCheckout({ paymentId: "p-9" } as any, { secret: "" }, "https://shop.test");
  eqJson(out.url, "https://shop.test/pay/stand-in?session=standin_p-9", "the stand-in sends the person to the app's own page");
  const chosen = await pay.adapterFor();
  ok(chosen.adapter.provider === "stand_in" && !chosen.live && /No payment service is connected/.test(chosen.notice), "with nothing connected the stand-in takes it and says so");
}
done("a payment is believed only from a signed event");
