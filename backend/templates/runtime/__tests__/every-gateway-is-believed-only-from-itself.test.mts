/**
 * Razorpay and PayPal beside Stripe: each believes a call only on its own
 * signature, reads its events into the application's words (a one-time
 * payment, a refund, a subscription that changed), and talks to its API in
 * the shapes the gateway documents. Money is converted per currency — no
 * decimals for yen, three for dinars. A payer is routed to the domestic
 * gateway at home and the international one abroad. Runs the SHIPPED modules,
 * with `fetch` recorded.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import crypto from "node:crypto";

installHarness({ stubs: {
  "drizzle-orm": "export const sql = Object.assign((s, ...v) => ({ s, v }), { join: (a) => a });",
  "@/db": "export const db = { async execute(q) { return globalThis.__dbExec ? globalThis.__dbExec(q) : []; } };",
  "@/lib/integrations/connected": "export function connectedService() { return undefined; }",
  "@/lib/integrations/resolver": "export async function getSecret(_p, k) { return globalThis.__env?.[k]; }",
  "@/lib/payments-config": "export const PAYMENTS = globalThis.__payments ?? { needed: false, gateways: [], plans: [] };",
  "@/lib/events/bus": "export async function emitEventAndProcess(t, o) { return globalThis.__emit ? globalThis.__emit(t, o) : { id: 'e1' }; }",
} });

const calls: Array<{ url: string; method: string; headers: Record<string, string>; body: string }> = [];
let answer: (url: string, init: any) => { status: number; body: any } = () => ({ status: 200, body: {} });
(globalThis as any).fetch = async (url: string, init: any = {}) => {
  const headers: Record<string, string> = {};
  for (const [k, v] of Object.entries(init.headers ?? {})) headers[k.toLowerCase()] = String(v);
  calls.push({ url: String(url), method: String(init.method ?? "GET"), headers, body: String(init.body ?? "") });
  const a = answer(String(url), init);
  return new Response(JSON.stringify(a.body), { status: a.status, headers: { "content-type": "application/json" } });
};

const units: any = await import("../payments/units.ts");
eqJson([units.toMinor(12.5, "INR"), units.toMinor(1200, "JPY"), units.toMinor(1.25, "KWD"), units.toMinor(9.999, "BHD")], [1250, 1200, 1250, 10000],
  "minor units: two decimals, none for yen, three (to the ten) for dinars");
eqJson([units.toMajor(1250, "KWD"), units.toMajor(1200, "JPY"), units.toMajor(499900, "INR")], [1.25, 1200, 4999], "and back to major");

// --- Razorpay -------------------------------------------------------------
const { razorpayAdapter, hmacHex, subscriptionSignatureOk }: any = await import("../payments/razorpay.ts");
const rzp = { secret: "rzpsecret", keyId: "rzp_test_K1" };
{
  answer = () => ({ status: 200, body: { id: "order_9", amount: 49900, currency: "INR", status: "created" } });
  const out = await razorpayAdapter.createCheckout({ paymentId: "11111111-2222-3333-4444-555555555555", amountMinor: 49900, currency: "inr",
    successUrl: "https://a/s", cancelUrl: "https://a/c", metadata: { entity: "Order" } }, rzp, "https://shop.test");
  const c = calls.at(-1)!;
  ok(c.url === "https://api.razorpay.com/v1/orders" && c.method === "POST", "an order is created at Razorpay");
  ok(c.headers.authorization === "Basic " + Buffer.from("rzp_test_K1:rzpsecret").toString("base64"), "with Basic auth of the key id and secret");
  const sent = JSON.parse(c.body);
  eqJson([sent.amount, sent.currency, sent.receipt.length <= 40, sent.notes.paymentId], [49900, "INR", true, "11111111-2222-3333-4444-555555555555"],
    "in paise, its currency, a receipt Razorpay accepts, and the ledger's id in its notes");
  ok(!("payment_capture" in sent), "no field Razorpay does not document");
  eqJson([out.providerRef, out.url], ["order_9", "https://shop.test/pay/razorpay?payment=11111111-2222-3333-4444-555555555555"],
    "the payer goes to the app's own page, which opens Razorpay's window");
}
{
  const row = { id: "p1", providerRef: "order_9", amountMinor: 49900, currency: "INR", metadata: {} };
  const good = hmacHex("rzpsecret", "order_9|pay_1");
  let threw = "";
  try { await razorpayAdapter.confirm(row, { razorpay_payment_id: "pay_1", razorpay_order_id: "order_9", razorpay_signature: hmacHex("other", "order_9|pay_1") }, rzp); }
  catch (e) { threw = String((e as Error).message); }
  ok(/signature did not check out/.test(threw), "a forged signature is refused before Razorpay is even asked");
  threw = "";
  try { await razorpayAdapter.confirm({ ...row, providerRef: "order_8" }, { razorpay_payment_id: "pay_1", razorpay_order_id: "order_9", razorpay_signature: good }, rzp); }
  catch (e) { threw = String((e as Error).message); }
  ok(/did not check out/.test(threw), "the signature is checked against OUR order, not the one the browser sent");
  let n = 0;
  answer = (url) => {
    n += 1;
    if (url.endsWith("/capture")) return { status: 200, body: { id: "pay_1", status: "captured", amount: 49900, currency: "INR", order_id: "order_9" } };
    return { status: 200, body: { id: "pay_1", status: "authorized", amount: 49900, currency: "INR", order_id: "order_9" } };
  };
  const out = await razorpayAdapter.confirm(row, { razorpay_payment_id: "pay_1", razorpay_signature: good }, rzp);
  eqJson([out.status, out.amountMinor, out.currency, out.metadata.providerPayment, n], ["succeeded", 49900, "INR", "pay_1", 2],
    "a signed, authorised payment is read, captured and paid");
  answer = () => ({ status: 200, body: { id: "pay_1", status: "captured", amount: 49900, currency: "INR", order_id: "order_OTHER" } });
  threw = "";
  try { await razorpayAdapter.confirm(row, { razorpay_payment_id: "pay_1", razorpay_signature: good }, rzp); } catch (e) { threw = String((e as Error).message); }
  ok(/another order/.test(threw), "a payment of another order is not this one");
}
{
  const raw = JSON.stringify({ event: "payment.captured", payload: { payment: { entity: { id: "pay_1", order_id: "order_9", amount: 49900, currency: "INR", notes: { paymentId: "p1" } } } } });
  const sig = crypto.createHmac("sha256", "whsec").update(raw).digest("hex");
  ok(razorpayAdapter.verifyWebhook(raw, new Headers({ "x-razorpay-signature": sig, "x-razorpay-event-id": "ev1" }), "whsec").ok, "a signed webhook is believed");
  ok(!razorpayAdapter.verifyWebhook(raw + " ", new Headers({ "x-razorpay-signature": sig }), "whsec").ok, "a changed body is not");
  ok(!razorpayAdapter.verifyWebhook(raw, new Headers(), "whsec").ok, "an unsigned one is not");
  const ev = razorpayAdapter.normalizeEvent(JSON.parse(raw));
  eqJson([ev.type, ev.providerRef, ev.paymentId, ev.amountMinor, ev.metadata.providerPayment], ["payment.succeeded", "order_9", "p1", 49900, "pay_1"], "captured is paid");
  const sub = razorpayAdapter.normalizeEvent({ event: "subscription.charged", payload: { subscription: { entity: { id: "sub_7", notes: { subscriptionId: "s-1" } } },
    payment: { entity: { id: "pay_2", amount: 49900, currency: "INR" } } } });
  eqJson([sub.type, sub.providerRef, sub.subscriptionId], ["subscription.updated", "sub_7", "s-1"], "a charged subscription is a subscription that changed, not a one-time payment");
  eqJson(razorpayAdapter.normalizeEvent({ event: "payment.captured", payload: { payment: { entity: { id: "pay_3", amount: 1, currency: "INR" } } } }), null,
    "a payment with no order (a subscription's own charge) is left to its subscription event");
  ok(subscriptionSignatureOk("rzpsecret", "sub_7", "pay_2", hmacHex("rzpsecret", "pay_2|sub_7")), "a subscription's checkout signature is payment|subscription");
  ok(!subscriptionSignatureOk("rzpsecret", "sub_8", "pay_2", hmacHex("rzpsecret", "pay_2|sub_7")), "for OUR subscription only");
}
{
  answer = (url) => url.endsWith("/plans") ? { status: 200, body: { id: "plan_1" } } : { status: 200, body: { id: "sub_7", short_url: "https://rzp.io/x" } };
  const ref = await razorpayAdapter.subscriptions.ensurePlan({ key: "k", planId: "pro", name: "Pro", interval: "month", intervalCount: 1, amountMinor: 49900, currency: "INR", trialDays: 0 }, rzp);
  const plan = JSON.parse(calls.at(-1)!.body);
  eqJson([ref, plan.period, plan.interval, plan.item.amount, plan.item.currency], ["plan_1", "monthly", 1, 49900, "INR"], "a plan is made in Razorpay's words");
  await razorpayAdapter.subscriptions.ensurePlan({ key: "k", planId: "d", name: "Daily", interval: "day", intervalCount: 1, amountMinor: 100, currency: "INR", trialDays: 0 }, rzp);
  eqJson(JSON.parse(calls.at(-1)!.body).interval, 7, "a daily plan is at least seven days, as Razorpay requires");
  const started = await razorpayAdapter.subscriptions.start({ subscriptionId: "s-1", planRef: "plan_1", plan: { interval: "month", trialDays: 14 } as any,
    successUrl: "x", cancelUrl: "y", metadata: {} }, rzp, "https://shop.test");
  const body = JSON.parse(calls.at(-1)!.body);
  eqJson([started.providerRef, body.plan_id, body.total_count > 0, body.notes.subscriptionId, body.customer_notify, typeof body.start_at],
    ["sub_7", "plan_1", true, "s-1", 1, "number"], "a subscription carries our id, a cycle count, and a trial as its start");
  ok(started.url.endsWith("/pay/razorpay?subscription=s-1"), "and is authorised in Razorpay's window on the app's page");
}

// --- PayPal ---------------------------------------------------------------
const { paypalAdapter, money, minorOf }: any = await import("../payments/paypal.ts");
const pp = { secret: "ppsecret", keyId: "ppclient", env: "sandbox" };
eqJson([money(1250, "USD"), money(1200, "JPY"), money(150000, "HUF")], ["12.50", "1200", "1500"], "PayPal's decimal strings, whole where PayPal wants whole");
eqJson([minorOf("12.50", "USD"), minorOf("1200", "JPY")], [1250, 1200], "and back");
{
  calls.length = 0;
  answer = (url) => url.endsWith("/oauth2/token") ? { status: 200, body: { access_token: "TOK", expires_in: 3000 } }
    : { status: 201, body: { id: "ORDER1", status: "PAYER_ACTION_REQUIRED", links: [{ rel: "payer-action", href: "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1" }] } };
  const out = await paypalAdapter.createCheckout({ paymentId: "p2", amountMinor: 1250, currency: "usd", successUrl: "https://a/s", cancelUrl: "https://a/c", metadata: {} }, pp, "https://a");
  ok(calls[0].url === "https://api-m.sandbox.paypal.com/v1/oauth2/token" && calls[0].body === "grant_type=client_credentials", "sandbox keys get a sandbox token");
  const order = JSON.parse(calls[1].body);
  eqJson([order.intent, order.purchase_units[0].amount, order.purchase_units[0].custom_id, calls[1].headers["paypal-request-id"]],
    ["CAPTURE", { currency_code: "USD", value: "12.50" }, "p2", "order-p2"], "an order in PayPal's words, carrying the ledger's id, idempotent");
  eqJson([out.providerRef, out.url.startsWith("https://www.sandbox.paypal.com/")], ["ORDER1", true], "the payer approves on PayPal's page");
  await paypalAdapter.createCheckout({ paymentId: "p3", amountMinor: 100, currency: "USD", successUrl: "s", cancelUrl: "c", metadata: {} }, pp, "https://a");
  eqJson(calls.filter((c) => c.url.endsWith("/oauth2/token")).length, 1, "the token is reused while it is good");
}
{
  answer = (url) => url.endsWith("/capture")
    ? { status: 201, body: { id: "ORDER1", status: "COMPLETED", purchase_units: [{ payments: { captures: [{ id: "CAP1", status: "DECLINED", amount: { currency_code: "USD", value: "12.50" } }] } }] } }
    : { status: 200, body: {} };
  const declined = await paypalAdapter.confirm({ id: "p2", providerRef: "ORDER1", amountMinor: 1250, currency: "USD", metadata: {} }, {}, pp);
  eqJson(declined.status, "failed", "a capture PayPal declined is a failure, though PayPal answered 201");
  answer = (url) => url.endsWith("/capture")
    ? { status: 422, body: { name: "UNPROCESSABLE_ENTITY", details: [{ issue: "ORDER_ALREADY_CAPTURED" }] } }
    : { status: 200, body: { id: "ORDER1", status: "COMPLETED", purchase_units: [{ amount: { currency_code: "USD", value: "12.50" }, payments: { captures: [{ id: "CAP1", status: "COMPLETED", amount: { currency_code: "USD", value: "12.50" } }] } }] } };
  const again = await paypalAdapter.confirm({ id: "p2", providerRef: "ORDER1", amountMinor: 1250, currency: "USD", metadata: {} }, {}, pp);
  eqJson([again.status, again.amountMinor, again.metadata.providerPayment], ["succeeded", 1250, "CAP1"], "captured already (the webhook came first): the order says it is paid");
}
{
  const raw = '{"id":"WH-1","event_type":"PAYMENT.CAPTURE.COMPLETED","resource":{"id":"CAP1","custom_id":"p2","amount":{"currency_code":"USD","value":"12.50"},"supplementary_data":{"related_ids":{"order_id":"ORDER1"}}}}';
  const hdrs = new Headers({ "paypal-auth-algo": "SHA256withRSA", "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT", "paypal-transmission-id": "t1",
    "paypal-transmission-sig": "sig", "paypal-transmission-time": "2026-10-30T10:00:00Z" });
  let verifyBody = "";
  answer = (url, init) => {
    if (url.endsWith("/verify-webhook-signature")) { verifyBody = String(init.body); return { status: 200, body: { verification_status: "SUCCESS" } }; }
    return { status: 200, body: { access_token: "TOK", expires_in: 3000 } };
  };
  const v = await paypalAdapter.verifyWebhook(raw, hdrs, "WHID", pp);
  ok(v.ok && v.eventId === "WH-1", "PayPal confirms the signature");
  ok(verifyBody.includes(`"webhook_event":${raw}}`) && verifyBody.includes('"webhook_id":"WHID"'), "with the event exactly as it arrived, and the app's webhook id");
  answer = (url) => url.endsWith("/verify-webhook-signature") ? { status: 200, body: { verification_status: "FAILURE" } } : { status: 200, body: { access_token: "TOK" } };
  ok(!(await paypalAdapter.verifyWebhook(raw, hdrs, "WHID", pp)).ok, "and refuses what PayPal does not confirm");
  ok(!(await paypalAdapter.verifyWebhook(raw, new Headers({ ...Object.fromEntries(hdrs), "paypal-cert-url": "https://evil.example/cert" }), "WHID", pp)).ok,
    "a certificate not at paypal.com is not even asked about");
  const ev = paypalAdapter.normalizeEvent(JSON.parse(raw));
  eqJson([ev.type, ev.providerRef, ev.paymentId, ev.amountMinor], ["payment.succeeded", "ORDER1", "p2", 1250], "a completed capture is paid, under its order");
  const sub = paypalAdapter.normalizeEvent({ event_type: "BILLING.SUBSCRIPTION.ACTIVATED", resource: { id: "I-SUB", custom_id: "s-9" } });
  eqJson([sub.type, sub.providerRef, sub.subscriptionId], ["subscription.updated", "I-SUB", "s-9"], "a subscription event names ours");
  const renew = paypalAdapter.normalizeEvent({ event_type: "PAYMENT.SALE.COMPLETED", resource: { id: "S1", billing_agreement_id: "I-SUB" } });
  eqJson([renew.type, renew.providerRef], ["subscription.updated", "I-SUB"], "a renewal's sale is its subscription changing");
}

// --- Stripe subscriptions -------------------------------------------------
const { stripeAdapter }: any = await import("../payments/stripe.ts");
{
  const s = stripeAdapter.normalizeEvent({ type: "checkout.session.completed", data: { object: { id: "cs_1", mode: "subscription", payment_status: "paid",
    subscription: "sub_1", client_reference_id: "s-3", metadata: {} } } });
  eqJson([s.type, s.providerRef, s.subscriptionId], ["subscription.updated", "sub_1", "s-3"], "a subscription's checkout is never read as a one-time payment");
  const inv = stripeAdapter.normalizeEvent({ type: "invoice.payment_failed", data: { object: { parent: { subscription_details: { subscription: "sub_1", metadata: { subscriptionId: "s-3" } } } } } });
  eqJson([inv.type, inv.providerRef, inv.subscriptionId], ["subscription.updated", "sub_1", "s-3"], "a failed renewal on the newest API shape");
  answer = (url) => url.includes("/prices?") ? { status: 200, body: { data: [{ id: "price_existing" }] } } : { status: 200, body: { id: "price_new" } };
  calls.length = 0;
  const ref = await stripeAdapter.subscriptions.ensurePlan({ key: "forge-app-pro-month1-USD-900-t0", planId: "pro", name: "Pro", interval: "month", intervalCount: 1, amountMinor: 900, currency: "USD", trialDays: 0 }, { secret: "sk_test_x" });
  eqJson([ref, calls.length], ["price_existing", 1], "a price is found again by its lookup key, not made twice");
}

// --- Routing --------------------------------------------------------------
const { routeFor, currencyFor }: any = await import("../payments/routing.ts");
{
  const g = [
    { id: "r", provider: "razorpay", label: "Razorpay India", coverage: "domestic", homeCountry: "IN", currencies: ["INR"], integration: "razorpay" },
    { id: "s", provider: "stripe", label: "Stripe", coverage: "international", currencies: ["USD", "EUR", "AED", "INR"], integration: "stripe", isDefault: true },
    { id: "p", provider: "paypal", label: "PayPal", coverage: "international", currencies: ["USD", "EUR"], integration: "paypal" },
  ];
  eqJson([routeFor(g, "INR", "IN")?.id, routeFor(g, "INR", null)?.id, routeFor(g, "INR", "US")?.id, routeFor(g, "USD", "IN")?.id, routeFor(g, "AED", "AE")?.id, routeFor(g, "JPY", "JP")],
    ["r", "r", "s", "s", "s", null], "INR at home goes to Razorpay; abroad and other currencies to Stripe (the default); nobody takes JPY");
  eqJson([currencyFor(["INR", "USD"], "INR", "US"), currencyFor(["INR", "USD"], "INR", "FR"), currencyFor(["USD"], "INR", "IN")], ["USD", "INR", "USD"],
    "a payer sees their own currency when it is offered, else the app's");
}

// --- The ledger moves one way ---------------------------------------------
{
  const pay: any = await import("../payments/index.ts");
  eqJson(pay.MOVES.succeeded, ["pending", "failed", "cancelled"], "paid from waiting, or after a failed try on the same order");
  eqJson(pay.MOVES.failed, ["pending"], "a failure never undoes a payment");
  eqJson(pay.MOVES.refunded, ["succeeded", "partially_refunded"], "only what was paid is refunded");
  (globalThis as any).__env = {};
  const none = await pay.gatewayFor({ currency: "INR" });
  ok(none.adapter.provider === "stand_in" && /No payment gateway is connected/.test(none.notice), "with no gateway the stand-in takes it, and says so");
}

// --- Subscriptions: who has access ------------------------------------------
{
  const billing: any = await import("../payments/billing.ts");
  const day = 86_400_000;
  const now = Date.now();
  const row = (status: string, endInDays: number | null, cancelAtEnd = false) => ({ status, current_period_end: endInDays === null ? null : new Date(now + endInDays * day).toISOString(), cancel_at_period_end: cancelAtEnd });
  eqJson([billing.grants(row("active", 10)), billing.grants(row("active", -2)), billing.grants(row("active", -4)), billing.grants(row("trialing", 3)),
          billing.grants(row("past_due", -1)), billing.grants(row("past_due", -5)), billing.grants(row("cancelled", 5, true)), billing.grants(row("cancelled", -1, true)),
          billing.grants(row("cancelled", 5, false)), billing.grants(row("incomplete", null)), billing.grants(null)],
    [true, true, false, true, true, false, true, false, false, false, false],
    "active (with three days' grace), trialing, past due in grace, cancelled until the end it was paid to; nothing else");
  process.env.NEXTAUTH_SECRET = "s3cr3t";
  const token = billing.accessToken("user-1", row("active", 30));
  const [body, sig] = token.value.split(".");
  const [uid, until] = Buffer.from(body, "base64url").toString().split(".");
  ok(uid === "user-1" && Number(until) * 1000 <= now + billing.ACCESS_TTL_S * 1000 + 1000, "the access token names the person and lasts hours, not the whole period");
  ok(sig === crypto.createHmac("sha256", "s3cr3t").update(`${uid}.${until}`).digest("base64url"), "and is signed with the app's own secret");
  ok(billing.accessToken("user-1", row("cancelled", 5, false)) === null, "no token without access");
  const spec = billing.specFor({ id: "pro", name: "Pro", interval: "month", intervalCount: 1, prices: { KWD: 3.5 }, trialDays: 0, features: [] }, "kwd");
  eqJson([spec.amountMinor, spec.currency, spec.key.includes("KWD-3500")], [3500, "KWD", true], "a plan's price in fils, and a key that changes with it");
}

// --- Subscriptions: how one ends --------------------------------------------
{
  const billing: any = await import("../payments/billing.ts");
  const { stripeAdapter }: any = await import("../payments/stripe.ts");
  const { razorpayAdapter: rz }: any = await import("../payments/razorpay.ts");
  const day = 86_400_000;
  const t = (ms: number) => Math.floor(ms / 1000);
  const ended = t(Date.now() - 60_000), periodEnd = t(Date.now() + 20 * day);
  answer = () => ({ status: 200, body: { id: "sub_1", status: "canceled", ended_at: ended, current_period_end: periodEnd, cancel_at_period_end: true } });
  const st = await stripeAdapter.subscriptions.retrieve("sub_1", { secret: "sk_test_1" });
  ok(st.status === "cancelled" && Date.parse(st.currentPeriodEnd) === ended * 1000,
    "Stripe: a subscription cancelled now ended when Stripe says it ended, not at the period it was billed for");
  answer = () => ({ status: 200, body: { id: "sub_2", status: "active", current_period_end: periodEnd, cancel_at_period_end: true } });
  const waiting = await stripeAdapter.subscriptions.retrieve("sub_2", { secret: "sk_test_1" });
  ok(waiting.status === "active" && Date.parse(waiting.currentPeriodEnd) === periodEnd * 1000 && waiting.cancelAtPeriodEnd,
    "and one waiting for its period's end runs to it");
  answer = () => ({ status: 200, body: { id: "sub_R", status: "cancelled", ended_at: ended, current_end: periodEnd } });
  const r = await rz.subscriptions.retrieve("sub_R", { secret: "x", keyId: "rzp_test_1" });
  ok(r.status === "cancelled" && Date.parse(r.currentPeriodEnd) === ended * 1000, "Razorpay: the same, from its `ended_at`");

  // What cancel sends: to the gateway, and to the row.
  const writes: any[] = [];
  (globalThis as any).__dbExec = (q: any) => {
    const text = (q.s ?? []).join("?");
    if (/UPDATE forge_subscriptions SET status/.test(text)) { writes.push(q.v); return [{ id: "row-1", status: q.v[0], current_period_end: q.v[1], cancel_at_period_end: q.v[2] }]; }
    return [];
  };
  (globalThis as any).__env = { STRIPE_SECRET_KEY: "sk_test_1" };
  const base = { id: "row-1", user_id: "u", plan_id: "pro", provider: "stripe", provider_ref: "sub_9", currency: "USD", amount_minor: 500, interval: "month",
    current_period_end: new Date(Date.now() + 20 * day).toISOString(), checked_at: new Date().toISOString() };
  calls.length = 0;
  await billing.cancel({ ...base, status: "active", cancel_at_period_end: true }, true);
  await billing.cancel({ ...base, status: "cancelled", cancel_at_period_end: true }, true);
  await billing.cancel({ ...base, status: "expired", cancel_at_period_end: false }, true);
  ok(calls.length === 0 && writes.length === 0, "asked again to end at the period's end, or already over: nothing is sent, nothing written");
  answer = () => ({ status: 200, body: { id: "sub_9", status: "canceled", ended_at: t(Date.now()), current_period_end: periodEnd, cancel_at_period_end: true } });
  const now1 = Date.now();
  const after = await billing.cancel({ ...base, status: "active", cancel_at_period_end: true }, false);
  ok(calls.filter((c) => c.method === "DELETE").length === 1 && calls.at(-1)?.method === "DELETE" && calls.at(-1)?.url.endsWith("/subscriptions/sub_9"),
    "cancel now after cancel at the end: one DELETE to Stripe");
  ok(after.status === "cancelled" && Date.parse(after.current_period_end) >= now1 - 1000 && Date.parse(after.current_period_end) <= Date.now() + 1000
     && !billing.grants(after, Date.now() + 1000) && after.cancel_at_period_end === false,
    "and it ends now, whatever the earlier request said: no access, and no longer said to be ending at the period's end");
  calls.length = 0; writes.length = 0;
  const again = await billing.cancel({ ...base, status: "cancelled", cancel_at_period_end: true }, false);
  ok(calls.length === 0 && writes.length === 1 && !billing.grants(again, Date.now() + 1000),
    "cancel now on what is already cancelled: the gateway is not asked again, and access ends here");
  calls.length = 0; writes.length = 0;
  const si = await billing.cancel({ ...base, provider: "stand_in", provider_ref: null, status: "active", cancel_at_period_end: true }, false);
  ok(calls.length === 0 && !billing.grants(si, Date.now() + 1000), "the stand-in's cancel now ends it too");
  const kept = await billing.cancel({ ...base, provider: "stand_in", provider_ref: null, status: "active", cancel_at_period_end: false }, true);
  ok(writes.at(-1)[1] === null && kept.cancel_at_period_end === true, "and its cancel at the end keeps the end it has (sends no new one)");

  // Asked once an hour: when the row alone says no, its period has run out, or it has no end yet.
  calls.length = 0;
  answer = () => ({ status: 200, body: { id: "sub_9", status: "past_due", current_period_end: t(Date.now() - 10 * day) } });
  const noEnd = { ...base, status: "trialing", provider_ref: "sub_9", current_period_end: null, checked_at: new Date(Date.now() - 2 * 3_600_000).toISOString(), cancel_at_period_end: false };
  (globalThis as any).__dbExec = (q: any) => {
    const text = (q.s ?? []).join("?");
    if (/SELECT \* FROM forge_subscriptions WHERE user_id/.test(text)) return [noEnd];
    if (/UPDATE forge_subscriptions SET status/.test(text)) return [{ ...noEnd, status: q.v[0], current_period_end: q.v[1] ?? noEnd.current_period_end }];
    return [];
  };
  const held = await billing.hasAccess("u");
  ok(calls.length === 1 && held.ok === false, "a subscription with no end yet is asked about, and a first charge that never landed opens nothing");
  calls.length = 0;
  (globalThis as any).__dbExec = (q: any) => /SELECT \* FROM forge_subscriptions WHERE user_id/.test((q.s ?? []).join("?")) ? [{ ...noEnd, checked_at: new Date().toISOString() }] : [];
  await billing.hasAccess("u");
  ok(calls.length === 0, "but not more than once an hour");
  delete (globalThis as any).__dbExec;
}

// --- A plan the gateway no longer knows ---------------------------------------
{
  const billing: any = await import("../payments/billing.ts");
  const { GatewayError }: any = await import("../payments/http.ts");
  const said = (status: number, body: any) => new GatewayError(`gateway answered ${status}`, status, body);
  ok(billing.missingPlan(said(400, { error: { code: "resource_missing", param: "line_items[0][price]", message: "No such price: 'price_1'" } })),
    "Stripe's unknown price is a missing plan");
  ok(billing.missingPlan(said(400, { error: { message: "The price specified is inactive. This field only accepts active prices." } })), "and its archived one");
  ok(billing.missingPlan(said(400, { error: { code: "BAD_REQUEST_ERROR", description: "The id provided does not exist", field: "plan_id" } })), "Razorpay's");
  ok(billing.missingPlan(said(404, { name: "RESOURCE_NOT_FOUND", details: [{ field: "/plan_id", issue: "INVALID_RESOURCE_ID" }] })), "PayPal's");
  ok(!billing.missingPlan(said(400, { error: { message: "Invalid email address: x" } })) && !billing.missingPlan(said(500, { error: { message: "No such price" } }))
     && !billing.missingPlan(new Error("No such price")), "nothing else is: a bad email, a gateway outage, an error of ours");

  // The config module was read once, at the first import: its object is the app's config.
  const { PAYMENTS: cfg }: any = await import("@/lib/payments-config");
  Object.assign(cfg, { needed: true, currency: "USD", models: ["subscription"], access: "none",
    gateways: [{ id: "g1", provider: "stripe", label: "Stripe", coverage: "both", currencies: ["USD"], integration: "stripe", isDefault: true }],
    plans: [{ id: "pro", name: "Pro", interval: "month", intervalCount: 1, prices: { USD: 5 }, trialDays: 0, features: [] }] });
  const refs: Record<string, string> = {};
  const keysSeen: string[] = [];
  (globalThis as any).__dbExec = (q: any) => {
    const text = (q.s ?? []).join("?");
    if (/SELECT \* FROM forge_subscriptions WHERE user_id/.test(text)) return [];
    if (/SELECT ref FROM forge_plan_refs/.test(text)) { keysSeen.push(q.v[0]); return refs[q.v[0]] ? [{ ref: refs[q.v[0]] }] : []; }
    if (/DELETE FROM forge_plan_refs/.test(text)) { delete refs[q.v[0]]; return []; }
    if (/INSERT INTO forge_plan_refs/.test(text)) { refs[q.v[0]] ??= q.v[2]; return []; }
    if (/INSERT INTO forge_subscriptions/.test(text)) return [{ id: "11111111-1111-4111-8111-111111111111" }];
    return [];
  };
  (globalThis as any).__env = { STRIPE_SECRET_KEY: "sk_test_accountA" };
  let made = 0;
  answer = (url: string) => {
    if (url.includes("/prices?")) return { status: 200, body: { data: [] } };
    if (url.endsWith("/prices")) { made++; return { status: 200, body: { id: `price_${made}` } }; }
    if (url.includes("/checkout/sessions")) {
      return made === 1 && !keysSeen.some((k) => k.includes("again"))
        ? { status: 400, body: { error: { code: "resource_missing", param: "line_items[0][price]", message: "No such price" } } }
        : { status: 200, body: { id: "cs_test_9", url: "https://checkout.stripe.test/cs_test_9" } };
    }
    return { status: 200, body: {} };
  };
  // A ref kept from before is stale: Stripe refuses it, the plan is made again once, the payer goes on.
  const pre = `stripe:${crypto.createHash("sha256").update("sk_test_accountA").digest("hex").slice(0, 12)}:`;
  const planKey = billing.specFor(cfg.plans[0], "USD").key;
  refs[pre + planKey] = "price_gone";
  calls.length = 0;
  answer = ((orig) => (url: string, init: any) => url.includes("/checkout/sessions") && String(init?.body ?? "").includes("price_gone")
    ? { status: 400, body: { error: { code: "resource_missing", param: "line_items[0][price]", message: "No such price: 'price_gone'" } } }
    : url.includes("/checkout/sessions") ? { status: 200, body: { id: "cs_test_9", url: "https://checkout.stripe.test/cs_test_9" } } : orig(url, init))(answer);
  const out = await billing.subscribe({ user: { id: "u1", email: "a@b.test" }, planId: "pro", currency: "USD", origin: "https://app.test" });
  const sessions = calls.filter((c) => c.url.includes("/checkout/sessions"));
  ok(out.url.includes("cs_test_9") && sessions.length === 2 && sessions[1].body.includes("price_1"),
    "a stale plan id is made again once and the payer goes on to pay");
  ok(calls.some((c) => c.url.endsWith("/prices") && c.body.includes("transfer_lookup_key=true")), "the new price takes the lookup key over");
  ok(refs[pre + planKey] === "price_1", "and the new id is what is kept");
  // Keys of another account: another plan id, not the first account's.
  (globalThis as any).__env = { STRIPE_SECRET_KEY: "sk_test_accountB" };
  keysSeen.length = 0;
  await billing.subscribe({ user: { id: "u1", email: "a@b.test" }, planId: "pro", currency: "USD", origin: "https://app.test" });
  ok(keysSeen.length > 0 && keysSeen.every((k) => !k.startsWith(pre)) && !keysSeen.some((k) => k.includes("sk_test")),
    "keys of another account look up their own plan, and the key is never written down");
  delete (globalThis as any).__dbExec;
  Object.assign(cfg, { needed: false, gateways: [], plans: [] });
}

// --- A refund is for what it says ------------------------------------------------
{
  const { paypalAdapter }: any = await import("../payments/paypal.ts");
  const pp = { secret: "pp-secret", keyId: "pp-client", env: "sandbox" };
  calls.length = 0;
  answer = (url: string) => url.includes("/oauth2/token") ? { status: 200, body: { access_token: "A", expires_in: 3000 } }
    : url.includes("/refund") ? { status: 201, body: { id: "RF1", status: "COMPLETED" } } : { status: 200, body: {} };
  await paypalAdapter.refund({ providerRef: "ORDER1", amountMinor: 10000, currency: "INR", metadata: { providerPayment: "CAP1" } }, pp);
  const part = calls.find((c) => c.url.endsWith("/v2/payments/captures/CAP1/refund"));
  ok(!!part && JSON.parse(part.body).amount?.value === "100.00" && JSON.parse(part.body).amount?.currency_code === "INR",
    "PayPal: a partial refund sends its amount and currency (PayPal refunds everything when none is sent)");
  calls.length = 0;
  answer = (url: string) => url.includes("/oauth2/token") ? { status: 200, body: { access_token: "A", expires_in: 3000 } }
    : url.endsWith("/v2/payments/captures/CAP2") ? { status: 200, body: { id: "CAP2", amount: { value: "25.00", currency_code: "USD" } } }
    : url.includes("/refund") ? { status: 201, body: { id: "RF2", status: "COMPLETED" } } : { status: 200, body: {} };
  await paypalAdapter.refund({ providerRef: "ORDER2", amountMinor: 500, metadata: { providerPayment: "CAP2" } }, pp);
  const asked = calls.find((c) => c.url.endsWith("/v2/payments/captures/CAP2/refund"));
  ok(!!asked && JSON.parse(asked.body).amount?.currency_code === "USD" && JSON.parse(asked.body).amount?.value === "5.00",
    "an engine that sends no currency: it is read off the capture first");
  calls.length = 0;
  answer = (url: string) => url.includes("/oauth2/token") ? { status: 200, body: { access_token: "A", expires_in: 3000 } } : { status: 200, body: {} };
  let refused = false;
  try { await paypalAdapter.refund({ providerRef: "ORDER3", amountMinor: 500, metadata: { providerPayment: "CAP3" } }, pp); } catch { refused = true; }
  ok(refused && !calls.some((c) => c.url.includes("/refund")), "and when it cannot be known, nothing is refunded (never the whole for a part)");
}

// --- An ending plan is still held -----------------------------------------------
{
  const billing: any = await import("../payments/billing.ts");
  const { PAYMENTS: cfg }: any = await import("@/lib/payments-config");
  Object.assign(cfg, { needed: true, currency: "USD", models: ["subscription"], access: "none",
    gateways: [{ id: "g1", provider: "stripe", label: "Stripe", coverage: "both", currencies: ["USD"], integration: "stripe", isDefault: true }],
    plans: [{ id: "pro", name: "Pro", interval: "month", intervalCount: 1, prices: { USD: 5 }, trialDays: 0, features: [] }] });
  (globalThis as any).__env = { STRIPE_SECRET_KEY: "sk_test_1" };
  const end = new Date(Date.now() + 20 * 86_400_000).toISOString();
  for (const held of [{ status: "active", cancel_at_period_end: true }, { status: "cancelled", cancel_at_period_end: true }]) {
    (globalThis as any).__dbExec = (q: any) => /SELECT \* FROM forge_subscriptions WHERE user_id/.test((q.s ?? []).join("?"))
      ? [{ id: "r1", user_id: "u1", plan_id: "pro", provider: "stripe", current_period_end: end, ...held }] : [];
    calls.length = 0;
    let said = "";
    try { await billing.subscribe({ user: { id: "u1" }, planId: "pro", currency: "USD", origin: "https://app.test" }); } catch (e) { said = String((e as Error).message); }
    ok(/already hold this plan until its period ends/.test(said) && calls.length === 0,
      `the same plan, ${held.status} and ending, is not taken (and charged) again before it ends`);
  }
  delete (globalThis as any).__dbExec;
  Object.assign(cfg, { needed: false, gateways: [], plans: [] });
}

// --- A subscription the gateway no longer knows -------------------------------------
{
  const billing: any = await import("../payments/billing.ts");
  const { GatewayError }: any = await import("../payments/http.ts");
  const said = (status: number, body: any) => new GatewayError(`gateway answered ${status}`, status, body);
  ok(billing.missingSubscription(said(404, { error: { code: "resource_missing", param: "id", message: "No such subscription: 'sub_9'" } })), "Stripe's unknown subscription");
  ok(billing.missingSubscription(said(400, { error: { code: "BAD_REQUEST_ERROR", description: "The id provided does not exist" } })), "Razorpay's");
  ok(billing.missingSubscription(said(404, { name: "RESOURCE_NOT_FOUND", details: [{ issue: "INVALID_RESOURCE_ID" }] })), "PayPal's");
  ok(!billing.missingSubscription(said(400, { error: { message: "This subscription has already been canceled." } }))
     && !billing.missingSubscription(said(400, { error: { code: "BAD_REQUEST_ERROR", description: "Subscription is not cancellable in cancelled status." } }))
     && !billing.missingSubscription(said(500, { error: { message: "No such subscription" } })) && !billing.missingSubscription(new Error("No such subscription")),
    "nothing else is: one already over, a gateway outage, an error of ours");

  const day = 86_400_000;
  const end = new Date(Date.now() + 20 * day).toISOString();
  const base = { id: "row-1", user_id: "u", plan_id: "pro", provider: "stripe", provider_ref: "sub_gone", currency: "USD", amount_minor: 500, interval: "month",
    status: "active", current_period_end: end, cancel_at_period_end: false, checked_at: new Date().toISOString() };
  const writes: any[] = [];
  (globalThis as any).__dbExec = (q: any) => {
    const text = (q.s ?? []).join("?");
    if (/UPDATE forge_subscriptions SET status/.test(text)) {
      writes.push(q.v);
      return [{ ...base, status: q.v[0], current_period_end: q.v[1] ?? base.current_period_end, cancel_at_period_end: q.v[2] }];
    }
    return [];
  };
  (globalThis as any).__env = { STRIPE_SECRET_KEY: "sk_test_1" };
  answer = () => ({ status: 404, body: { error: { code: "resource_missing", param: "id", message: "No such subscription: 'sub_gone'" } } });
  const now = await billing.cancel({ ...base, cancel_at_period_end: true }, false);
  ok(now.status === "cancelled" && now.cancel_at_period_end === false && !billing.grants(now, Date.now() + 1000),
    "cancel now, and the gateway does not know it: it ends here, not refused at every try");
  writes.length = 0;
  const atEnd = await billing.cancel(base, true);
  ok(atEnd.status === "cancelled" && atEnd.cancel_at_period_end === true && writes[0][1] === null
     && billing.grants(atEnd) && !billing.grants(atEnd, Date.parse(end) + 1000),
    "cancel at the end: what was paid for stays open until its end, and then it is over (it cannot renew)");
  const noEnd = await billing.cancel({ ...base, current_period_end: null }, true);
  ok(!billing.grants(noEnd, Date.now() + 1000), "and one with no paid end yet ends now");
  answer = () => ({ status: 500, body: { error: { message: "Something went wrong on Stripe's end." } } });
  let threw = false;
  try { await billing.cancel(base, false); } catch { threw = true; }
  ok(threw, "a gateway outage is still an error to try again, not an ending");
  delete (globalThis as any).__dbExec;
}
// --- The live app never takes a payment through the stand-in --------------------------
{
  const pay: any = await import("../payments/index.ts");
  const billing: any = await import("../payments/billing.ts");
  const { PAYMENTS: cfg }: any = await import("@/lib/payments-config");
  const env = process.env as any;
  const was = { side: env.FORGE_PAYMENTS_SIDE, vercel: env.VERCEL_ENV };
  Object.assign(cfg, { needed: true, currency: "USD", models: ["one_time"], access: "none",
    gateways: [{ id: "g1", provider: "stripe", label: "Stripe US", coverage: "both", currencies: ["USD"], integration: "stripe", isDefault: true }], plans: [] });
  (globalThis as any).__env = {};
  env.FORGE_PAYMENTS_SIDE = "test";
  const test = await pay.gatewayFor({ currency: "USD" });
  ok(test.adapter.provider === "stand_in" && !test.live, "on the test side, a gateway without keys stands in, and says so");
  env.FORGE_PAYMENTS_SIDE = "production";
  let said = "";
  try { await pay.gatewayFor({ currency: "USD" }); } catch (e) { said = `${(e as Error).name}: ${(e as Error).message}`; }
  ok(/^PaymentsNotReady: Payments are not switched on/.test(said), "in production a gateway without live keys refuses — no stand-in, no free 'Paid'");
  ok(!/Stripe US|Settings|keys/.test(said), "and the payer is not told how the app is set up");
  Object.assign(cfg, { gateways: [] });
  said = "";
  try { await pay.gatewayFor({ currency: "USD" }); } catch (e) { said = (e as Error).name; }
  ok(said === "PaymentsNotReady", "and with no gateway chosen at all");
  (globalThis as any).__dbExec = (q: any) => /FROM forge_subscriptions WHERE id/.test((q.s ?? []).join("?"))
    ? [{ id: "11111111-1111-4111-8111-111111111111", user_id: "u1", provider: "stand_in", status: "incomplete", interval: "month", metadata: {} }] : [];
  ok(await billing.standInSettle("11111111-1111-4111-8111-111111111111", "u1", "paid") === null, "and the stand-in's 'Subscribed' opens no plan there");
  delete env.FORGE_PAYMENTS_SIDE;
  env.VERCEL_ENV = "production";
  ok(pay.liveSide(), "an app published before the side was written reads Vercel's production as live");
  env.VERCEL_ENV = "preview";
  ok(!pay.liveSide(), "and its preview as not");
  if (was.side === undefined) delete env.FORGE_PAYMENTS_SIDE; else env.FORGE_PAYMENTS_SIDE = was.side;
  if (was.vercel === undefined) delete env.VERCEL_ENV; else env.VERCEL_ENV = was.vercel;
  delete (globalThis as any).__dbExec;
  Object.assign(cfg, { needed: false, gateways: [], plans: [] });
}

// --- One signed event settles the order it is about, once, and the app is told ---------
{
  const pay: any = await import("../payments/index.ts");
  const rows: Record<string, any> = {
    X: { id: "aaaaaaaa-0000-4000-8000-00000000000a", provider: "razorpay", provider_ref: "order_X", status: "pending", amount_minor: 50000, currency: "INR", metadata: {} },
    Y: { id: "aaaaaaaa-0000-4000-8000-00000000000b", provider: "razorpay", provider_ref: "order_Y", status: "pending", amount_minor: 50000, currency: "INR", metadata: {} },
  };
  const byKey = (k: string) => Object.values(rows).find((r: any) => r.id === k || r.provider_ref === k);
  const emitted: string[] = [];
  (globalThis as any).__emit = (t: string, o: any) => { emitted.push(o.dedupeKey); return { id: "e" }; };
  (globalThis as any).__dbExec = (q: any) => {
    const text = (q.s ?? []).join("?");
    if (/SELECT \* FROM forge_payments WHERE/.test(text)) { const r = byKey(String(q.v[0])); return r ? [{ ...r, metadata: { ...r.metadata } }] : []; }
    if (/UPDATE forge_payments SET status = .* RETURNING id/s.test(text)) {
      // `sql.join` hands the statuses it may move from as fragments, each holding its value.
      const r = byKey(String(q.v[2])); const from = (q.v[3] ?? []).map((f: any) => f?.v?.[0]);
      if (r && from.includes(r.status)) { r.status = q.v[0]; if (q.v[1]) r.provider_ref = q.v[1]; return [{ id: r.id }]; }
      return [];
    }
    if (/UPDATE forge_payments SET metadata/.test(text)) { const r = byKey(String(q.v[1])); if (r) Object.assign(r.metadata, JSON.parse(q.v[0])); return []; }
    return [];
  };
  // A payer's own notes on Y's payment name X: the event is Y's order.
  const out = await pay.settle("razorpay", { type: "payment.succeeded", providerRef: "order_Y", paymentId: rows.X.id, amountMinor: 50000, currency: "INR", metadata: {} });
  ok(out.paymentId === rows.Y.id && rows.Y.status === "succeeded" && rows.X.status === "pending" && rows.X.provider_ref === "order_X",
    "a payment whose notes name another order settles its own order, never the one it names");
  // Settled, and the app never heard: told when the gateway sends it again.
  emitted.length = 0;
  const again = await pay.settle("razorpay", { type: "payment.succeeded", providerRef: "order_Y", amountMinor: 50000, currency: "INR", metadata: {} });
  ok(again.moved === false && emitted.length === 1, "a payment already paid is told again (its event key keeps it to once in the app)");
  (globalThis as any).__emit = () => null;
  const lost = await pay.settle("razorpay", { type: "payment.succeeded", providerRef: "order_Y", amountMinor: 50000, currency: "INR", metadata: {} });
  ok(lost.told === false, "an event that could not be written is said, so the webhook answers 500 and the gateway sends it again");
  (globalThis as any).__emit = (t: string, o: any) => { emitted.push(o.dedupeKey); return { id: "e" }; };
  // Two partial refunds from Razorpay's dashboard, each its own event.
  emitted.length = 0;
  await pay.settle("razorpay", { type: "refund.succeeded", providerRef: "order_Y", paymentId: rows.Y.id, amountMinor: 20000, currency: "INR", metadata: { refundId: "rfnd_1" } });
  ok(rows.Y.status === "partially_refunded", "a first part refunded: partly refunded");
  await pay.settle("razorpay", { type: "refund.succeeded", providerRef: "order_Y", paymentId: rows.Y.id, amountMinor: 20000, currency: "INR", metadata: { refundId: "rfnd_1" } });
  ok(rows.Y.status === "partially_refunded" && Object.keys(rows.Y.metadata.refunds).length === 1, "the same refund delivered twice counts once");
  await pay.settle("razorpay", { type: "refund.succeeded", providerRef: "order_Y", paymentId: rows.Y.id, amountMinor: 30000, currency: "INR", metadata: { refundId: "rfnd_2" } });
  ok(rows.Y.status === "refunded", "the refunds adding up to the whole: refunded in full");
  ok(new Set(emitted).size === 2 && emitted[0] === emitted[1],
    "each refund is its own event to the app; the same refund again carries the same key (the bus keeps one)");
  delete (globalThis as any).__dbExec; delete (globalThis as any).__emit;
}
// --- A subscription is taken once, its trial once, and its grace from the failed charge ---
{
  const billing: any = await import("../payments/billing.ts");
  const { PAYMENTS: cfg }: any = await import("@/lib/payments-config");
  Object.assign(cfg, { needed: true, currency: "USD", models: ["subscription"], access: "none",
    gateways: [{ id: "g1", provider: "stripe", label: "Stripe", coverage: "both", currencies: ["USD"], integration: "stripe", isDefault: true }],
    plans: [{ id: "pro", name: "Pro", interval: "month", intervalCount: 1, prices: { USD: 5 }, trialDays: 14, features: [] }] });
  (globalThis as any).__env = { STRIPE_SECRET_KEY: "sk_test_trials" };
  const day = 86_400_000;
  let openCheckout = false, heldBefore = false;
  const keys: string[] = [];
  const closed: string[] = [];
  (globalThis as any).__dbExec = (q: any) => {
    const text = (q.s ?? []).join("?");
    if (/SELECT \* FROM forge_subscriptions WHERE user_id = \? AND plan_id/.test(text)) return openCheckout
      ? [{ id: "33333333-3333-4333-8333-333333333333", user_id: "u9", plan_id: "pro", provider: "stripe", provider_ref: "cs_open", status: "incomplete",
           currency: "USD", amount_minor: 500, interval: "month", current_period_end: null, cancel_at_period_end: false, metadata: {} }] : [];
    if (/SET status = 'expired', metadata/.test(text)) { closed.push(String(q.v.at(-1))); return []; }
    // A write answers the row as written (RETURNING *).
    if (/UPDATE forge_subscriptions SET status = \?/.test(text)) return [{ id: "33333333-3333-4333-8333-333333333333", user_id: "u9", plan_id: "pro",
      provider: "stripe", provider_ref: "cs_open", status: q.v[0], currency: "USD", amount_minor: 500, interval: "month",
      current_period_end: q.v[1], cancel_at_period_end: false, metadata: {} }];
    if (/SELECT \* FROM forge_subscriptions WHERE user_id/.test(text)) return [];
    if (/SELECT 1 FROM forge_subscriptions/.test(text)) return heldBefore ? [{ "?column?": 1 }] : [];
    if (/SELECT ref FROM forge_plan_refs/.test(text)) { keys.push(String(q.v[0])); return [{ ref: "price_x" }]; }
    if (/INSERT INTO forge_subscriptions/.test(text)) return [{ id: "22222222-2222-4222-8222-222222222222" }];
    return [];
  };
  answer = (url: string) => url.includes("/checkout/sessions/cs_open/expire") ? { status: 200, body: { id: "cs_open", status: "expired" } }
    : url.includes("/checkout/sessions/cs_open") ? { status: 200, body: { id: "cs_open", status: "open", payment_status: "unpaid" } }
    : url.includes("/checkout/sessions") ? { status: 200, body: { id: "cs_t", url: "https://checkout.stripe.test/cs_t" } } : { status: 200, body: {} };
  const go = () => billing.subscribe({ user: { id: "u9", email: "p@q.test" }, planId: "pro", currency: "USD", origin: "https://app.test" });
  openCheckout = true;
  calls.length = 0;
  const again = await go();
  ok(again.url.includes("cs_t") && calls.some((c) => c.url.endsWith("/checkout/sessions/cs_open/expire")) && closed.length === 1,
    "choosing the plan again closes the checkout left open at Stripe (it can never be completed too), and opens a new one");
  answer = (url: string) => url.includes("/subscriptions/sub_paid")
    ? { status: 200, body: { id: "sub_paid", status: "active", current_period_end: Math.floor(Date.now() / 1000) + 30 * 86400, cancel_at_period_end: false } }
    : url.includes("/checkout/sessions/cs_open")
    ? { status: 200, body: { id: "cs_open", status: "complete", payment_status: "paid", subscription: "sub_paid" } }
    : url.includes("/checkout/sessions") ? { status: 200, body: { id: "cs_t", url: "https://checkout.stripe.test/cs_t" } } : { status: 200, body: {} };
  let said = "";
  try { await go(); } catch (e) { said = (e as Error).message; }
  ok(/already hold this plan/.test(said), "an earlier checkout that was paid after all: the person holds the plan, and is not charged again");
  answer = (url: string) => url.includes("/checkout/sessions") ? { status: 200, body: { id: "cs_t", url: "https://checkout.stripe.test/cs_t" } } : { status: 200, body: {} };
  openCheckout = false;
  await go();
  ok(keys.at(-1)?.includes("-t14"), "someone new gets the plan's free trial");
  heldBefore = true;
  await go();
  ok(keys.at(-1)?.includes("-t0"), "someone who held a plan before pays from the first day (no second trial)");

  const now = Date.now();
  const late = { id: "r", user_id: "u", plan_id: "pro", provider: "stripe", status: "past_due", currency: "USD", amount_minor: 500, interval: "year",
    current_period_end: new Date(now + 300 * day).toISOString(), cancel_at_period_end: false, metadata: {} as any };
  ok(!billing.grants({ ...late, metadata: { pastDueSince: new Date(now - 5 * day).toISOString() } }),
    "a renewal that failed five days ago closes the app, though Stripe moved the period's end a year on");
  ok(billing.grants({ ...late, metadata: { pastDueSince: new Date(now - day).toISOString() } }), "within its grace it stays open");

  const env = process.env as any;
  const secretWas = env.NEXTAUTH_SECRET;
  env.NEXTAUTH_SECRET = "test-secret";
  const ending = { ...late, status: "active", interval: "month", cancel_at_period_end: true, current_period_end: new Date(now + 3_600_000).toISOString(), metadata: {} };
  const tok = billing.accessToken("u", ending);
  ok(tok && tok.maxAge <= 3600, "a plan ending in an hour opens the app for that hour, not its grace after");
  if (secretWas === undefined) delete env.NEXTAUTH_SECRET; else env.NEXTAUTH_SECRET = secretWas;

  // The plan that goes on is the one shown and cancelled, not the one ending.
  let ordered = "";
  (globalThis as any).__dbExec = (q: any) => { const text = (q.s ?? []).join("?"); if (/FROM forge_subscriptions WHERE user_id/.test(text)) ordered = text; return []; };
  await billing.current("u");
  ok(/cancel_at_period_end ASC, created_at DESC/.test(ordered) && /status = 'cancelled' AND cancel_at_period_end AND current_period_end > NOW\(\)/.test(ordered),
    "after a switch, the person's plan is the new one (the old one is ending); a plan ending but still paid for comes before one long over");

  // Resumed in Stripe's own portal: resumed here.
  const writes: any[] = [];
  (globalThis as any).__dbExec = (q: any) => { const text = (q.s ?? []).join("?"); if (/UPDATE forge_subscriptions SET status/.test(text)) { writes.push(q.v); return []; } return []; };
  answer = () => ({ status: 200, body: { id: "sub_r", status: "active", current_period_end: Math.floor((now + 20 * day) / 1000), cancel_at_period_end: false } });
  await billing.refresh({ ...ending, provider_ref: "sub_r" });
  ok(writes.at(-1)?.[2] === false, "a Stripe plan resumed in Stripe's portal is no longer 'ending' here");
  delete (globalThis as any).__dbExec;
  Object.assign(cfg, { needed: false, gateways: [], plans: [] });
}
done("every gateway is believed only from itself");
