/**
 * The SHIPPED push.ts: nothing is sent without the app's keys and the caller
 * is told; every subscribed device of the person gets the message, signed by
 * web-push; a device that answers 410 is forgotten. A person's PHONES are reached through Expo with no key of the app's own,
 * and a phone Expo says is gone is forgotten too.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

(globalThis as any).__rows = [
  { userId: "u1", endpoint: "https://push.test/a", p256dh: "pk", auth: "au" },
  { userId: "u1", endpoint: "https://push.test/gone", p256dh: "pk", auth: "au" },
];
(globalThis as any).__tokens = [] as any[];
(globalThis as any).__expo = [] as any[];
(globalThis as any).__sent = [] as any[];
(globalThis as any).__deleted = [] as any[];
(globalThis as any).__vapid = null;
installHarness({ stubs: {
  "@/db": `export const db = {
    select: () => ({ from: (t) => ({ where: async () => (t && t.__tbl === "tokens" ? globalThis.__tokens : globalThis.__rows) }) }),
    delete: () => ({ where: async (w) => { globalThis.__deleted.push(w); } }),
    execute: async () => [{ id: "u1" }],
  };`,
  "@/db/schema/_forge_push_subscriptions": `export const forgePushSubscriptions = { userId: "user_id", endpoint: "endpoint" };`,
  "@/db/schema/_forge_device_tokens": `export const forgeDeviceTokens = { __tbl: "tokens", userId: "user_id", token: "token" };`,
  "drizzle-orm": `export const eq = (c, v) => ({ eq: [c, v] }); export const inArray = (c, v) => ({ in: [c, v] }); export const sql = (s, ...v) => ({ s, v });`,
  "web-push": `export default { setVapidDetails: (s, pub, priv) => { globalThis.__vapid = { s, pub, priv }; },
    sendNotification: async (sub, body) => { if (sub.endpoint.endsWith("/gone")) { const e = new Error("gone"); e.statusCode = 410; throw e; } globalThis.__sent.push({ endpoint: sub.endpoint, body: JSON.parse(body) }); } };`,
}, redirect: { "@/lib/expo-push": new URL("../expo-push.ts", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1") } });
(globalThis as any).fetch = async (_url: string, init: any) => {
  const batch = JSON.parse(init.body);
  (globalThis as any).__expo.push(...batch);
  return { ok: true, status: 200, json: async () => ({ data: batch.map((m: any) => (m.to.endsWith("[gone]") ? { status: "error", details: { error: "DeviceNotRegistered" } } : { status: "ok" })) }) };
};

const push: any = await import("../push.ts");
const none = await push.sendPush({ userIds: ["u1"] }, { title: "Hi" }, {});
eqJson(none.sent, 0, "no keys: nothing sent");
ok(String(none.notice).includes("VAPID_PUBLIC_KEY"), "and the caller is told which names are unset");

const env = { VAPID_PUBLIC_KEY: "pub", VAPID_PRIVATE_KEY: "priv", VAPID_SUBJECT: "mailto:ops@acme.test" };
const out = await push.sendPush({ userIds: ["u1"] }, { title: "Shift change", body: "6am", link: "/shifts/1" }, env);
eqJson({ sent: out.sent, pruned: out.pruned }, { sent: 1, pruned: 1 }, "one device reached, one forgotten");
eqJson((globalThis as any).__vapid, { s: "mailto:ops@acme.test", pub: "pub", priv: "priv" }, "signed with the app's own keys");
eqJson((globalThis as any).__sent[0].body, { title: "Shift change", body: "6am", link: "/shifts/1" }, "the message as sent");
eqJson((globalThis as any).__deleted.length, 1, "the gone device's row is removed");
const nobody = await push.sendPush({ role: "Nurse" }, { title: "x" }, env);
ok(nobody.sent === 1, "a role fans out to its people");

// ---- phones ----
(globalThis as any).__tokens = [{ userId: "u1", token: "ExponentPushToken[ok]" }, { userId: "u1", token: "ExponentPushToken[gone]" }];
(globalThis as any).__sent.length = 0; (globalThis as any).__deleted.length = 0;
const phones = await push.sendPush({ userIds: ["u1"] }, { title: "New ride", body: "2 km away", link: "/" }, {});
eqJson({ sent: phones.sent, phones: phones.phones, web: phones.web, pruned: phones.pruned }, { sent: 1, phones: 1, web: 0, pruned: 1 }, "no keys for browsers, yet the phone is reached and the dead one forgotten");
ok(phones.notice === undefined, "and nothing is said, because something went");
eqJson((globalThis as any).__expo.map((m: any) => m.to), ["ExponentPushToken[ok]", "ExponentPushToken[gone]"], "both phones were sent the alert");
eqJson((globalThis as any).__deleted.length, 1, "the gone phone's row is removed");
const both = await push.sendPush({ userIds: ["u1"] }, { title: "x" }, env);
ok(both.web === 1 && both.phones === 1 && both.sent === 2, "a person with a browser and a phone gets both");
(globalThis as any).__tokens = [];
const bare = await push.sendPush({ userIds: ["u1"] }, { title: "x" }, {});
ok(bare.sent === 0 && String(bare.notice).includes("VAPID_PUBLIC_KEY"), "no browser and no phone: still told which keys are unset");
done();
