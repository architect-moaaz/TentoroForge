/**
 * The SHIPPED push.ts: nothing is sent without the app's keys and the caller
 * is told; every subscribed device of the person gets the message, signed by
 * web-push; a device that answers 410 is forgotten.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

(globalThis as any).__rows = [
  { userId: "u1", endpoint: "https://push.test/a", p256dh: "pk", auth: "au" },
  { userId: "u1", endpoint: "https://push.test/gone", p256dh: "pk", auth: "au" },
];
(globalThis as any).__sent = [] as any[];
(globalThis as any).__deleted = [] as any[];
(globalThis as any).__vapid = null;
installHarness({ stubs: {
  "@/db": `export const db = {
    select: () => ({ from: () => ({ where: async () => globalThis.__rows }) }),
    delete: () => ({ where: async (w) => { globalThis.__deleted.push(w); } }),
    execute: async () => [{ id: "u1" }],
  };`,
  "@/db/schema/_forge_push_subscriptions": `export const forgePushSubscriptions = { userId: "user_id", endpoint: "endpoint" };`,
  "drizzle-orm": `export const eq = (c, v) => ({ eq: [c, v] }); export const inArray = (c, v) => ({ in: [c, v] }); export const sql = (s, ...v) => ({ s, v });`,
  "web-push": `export default { setVapidDetails: (s, pub, priv) => { globalThis.__vapid = { s, pub, priv }; },
    sendNotification: async (sub, body) => { if (sub.endpoint.endsWith("/gone")) { const e = new Error("gone"); e.statusCode = 410; throw e; } globalThis.__sent.push({ endpoint: sub.endpoint, body: JSON.parse(body) }); } };`,
} });

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
done();
