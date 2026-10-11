/**
 * An outside system's call is believed only once its signature checks out,
 * a second delivery of the same call is recognised and not run twice, and a
 * stale or forged signature is refused. Runs the SHIPPED webhook route
 * against a stub bus that records what reached it.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import crypto from "node:crypto";

(globalThis as any).__EMITTED__ = [];
(globalThis as any).__SEEN__ = new Set<string>();
installHarness({ stubs: {
  "next/server": "export const NextResponse = { json: (body, init) => ({ status: init?.status ?? 200, body }) };",
  "@/lib/integrations/connected": 'export const INBOUND = { shop: { name: "Shop", provider: "shop", verify: "hmac_sha256", signingSecretRef: "SHOP_WEBHOOK_SECRET", events: ["order.paid"] }, bot: { name: "Bot", provider: "bot", verify: "bearer", signingSecretRef: "BOT_TOKEN", events: [] } };',
  "@/lib/integrations/providers": "export const PROVIDER_VERIFIERS = {}; export const PAYMENT_PROVIDERS = new Set();",
  "@/lib/events/bus": "export async function emitEventAndProcess(type, opts) { globalThis.__EMITTED__.push({ type, opts }); if (globalThis.__SEEN__.has(opts.dedupeKey)) return { duplicate: true }; globalThis.__SEEN__.add(opts.dedupeKey); return { id: 'evt-' + globalThis.__EMITTED__.length }; }",
  "@/lib/runtime-loader": "export async function initializeRuntime() {}",
} });

process.env.SHOP_WEBHOOK_SECRET = "s3cret";
process.env.BOT_TOKEN = "tok";
const route: any = await import("../api-webhooks/route.ts");
const sign = (raw: string, secret: string, t = Math.floor(Date.now() / 1000)) =>
  `t=${t},v1=${crypto.createHmac("sha256", secret).update(`${t}.${raw}`).digest("hex")}`;
const call = (slug: string, raw: string, headers: Record<string, string>) =>
  route.POST(new Request(`http://app.test/api/webhooks/${slug}`, { method: "POST", body: raw, headers }),
             { params: Promise.resolve({ integration: slug }) });

const raw = JSON.stringify({ id: "ord-1", type: "order.paid", total: 42 });
{
  const res = await call("shop", raw, { "x-signature": sign(raw, "s3cret") });
  eqJson(res.status, 202, "a signed call is accepted");
  eqJson((globalThis as any).__EMITTED__.at(-1).type, "shop.order.paid", "and put on the bus as the integration's event");
  eqJson((globalThis as any).__EMITTED__.at(-1).opts.dedupeKey, "shop:ord-1", "keyed by the delivery's own id");
}
{
  const res = await call("shop", raw, { "x-signature": sign(raw, "s3cret") });
  eqJson(res.status, 200, "the same delivery again is answered");
  eqJson(res.body.duplicate, true, "as a duplicate");
}
{
  const res = await call("shop", raw, { "x-signature": sign(raw, "wrong") });
  eqJson(res.status, 401, "a forged signature is refused");
  const stale = await call("shop", raw, { "x-signature": sign(raw, "s3cret", Math.floor(Date.now() / 1000) - 3600) });
  eqJson(stale.status, 401, "an hour-old signature is refused");
  eqJson(stale.body.error, "stale signature", "and says why");
  const none = await call("shop", raw, {});
  eqJson(none.status, 401, "no signature is refused");
}
{
  const res = await call("bot", "{}", { authorization: "Bearer tok" });
  eqJson(res.status, 202, "a bearer-verified integration accepts its token");
  const bad = await call("bot", "{}", { authorization: "Bearer nope" });
  eqJson(bad.status, 401, "and refuses another");
}
{
  const res = await call("nobody", raw, {});
  eqJson(res.status, 404, "an integration that does not call in is not an address");
  delete process.env.SHOP_WEBHOOK_SECRET;
  const unset = await call("shop", raw, { "x-signature": sign(raw, "s3cret") });
  eqJson(unset.status, 503, "a secret the environment lacks is said, never guessed");
  ok(String(unset.body.error).includes("SHOP_WEBHOOK_SECRET is not set"), "by name");
}
done("a webhook is verified before it is believed");
