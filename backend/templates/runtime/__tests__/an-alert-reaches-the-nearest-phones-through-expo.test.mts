/**
 * The phone side of push, with no network and no database: who is nearest to a pickup (from the live fleet), and what is posted
 * to Expo for them — the batches, the tokens that are forgotten, the words when Expo cannot be reached.
 * Self-contained (it imports only the two pure modules), so it runs on any node that strips types.
 */
import { nearest, distanceKm, validPlace, placeOf, whoIsNear } from "../tracking/nearest.ts";
import { sendExpo, expoMessages, validExpoToken, EXPO_BATCH, EXPO_SEND_URL } from "../expo-push.ts";
import { fleetPublish, fleetSnapshot, fleetOnDuty, fleetLeave, FLEET_TTL_MS } from "../tracking/hub.ts";

let failed = 0;
const ok = (c: unknown, what: string) => { console.log(`  ${c ? "ok  " : "FAIL"} ${what}`); if (!c) failed += 1; };
const eq = (a: unknown, b: unknown, what: string) => ok(JSON.stringify(a) === JSON.stringify(b), `${what}${JSON.stringify(a) === JSON.stringify(b) ? "" : `  (got ${JSON.stringify(a)}, wanted ${JSON.stringify(b)})`}`);

console.log("distance");
const pickup = { lat: 12.9716, lng: 77.5946 };
ok(Math.abs(distanceKm(pickup, pickup)) < 1e-9, "no distance to the same place");
ok(Math.abs(distanceKm({ lat: 0, lng: 0 }, { lat: 0, lng: 1 }) - 111.19) < 0.5, "a degree of longitude on the equator is about 111 km");
ok(validPlace(pickup) && !validPlace({ lat: 91, lng: 0 }) && !validPlace(null) && !validPlace({ lat: NaN, lng: 0 }), "a place is a real place");

console.log("the nearest on duty");
const now = 1_000_000;
const fleet = [
  { id: "d-far", who: "u-far", lat: 13.2, lng: 77.8, at: now - 1000 },
  { id: "d-near", who: "u-near", lat: 12.9720, lng: 77.5950, at: now - 1000 },
  { id: "d-mid", who: "u-mid", lat: 12.99, lng: 77.62, at: now - 1000 },
  { id: "d-stale", who: "u-stale", lat: 12.9717, lng: 77.5947, at: now - 600_000 },
  { id: "d-twice", who: "u-near", lat: 13.0, lng: 77.7, at: now - 1000 },
  { id: "d-nobody", who: "", lat: 12.9716, lng: 77.5946, at: now - 1000 },
];
eq(nearest(fleet, pickup, { now, limit: 2 }).map((n) => n.userId), ["u-stale", "u-near"], "closest first, each person once, no age limit asked");
eq(nearest(fleet, pickup, { now, limit: 5, maxAgeMs: 120_000 }).map((n) => n.userId), ["u-near", "u-mid", "u-far"], "someone who went quiet is not nearby");
eq(nearest(fleet, pickup, { now, limit: 5, maxAgeMs: 120_000, maxKm: 10 }).map((n) => n.userId), ["u-near", "u-mid"], "and nobody beyond the radius");
eq(nearest(fleet, pickup, { now, limit: 5, maxAgeMs: 120_000, exclude: ["u-near"] }).map((n) => n.userId), ["u-mid", "u-far"], "a person can be left out");
eq(nearest(fleet, { lat: 200, lng: 0 }, { now }), [], "no place, no one");
eq(nearest([], pickup, { now }), [], "an empty fleet is nobody");
ok(nearest(fleet, pickup, { now, limit: 0, maxAgeMs: 120_000 }).length === 1, "a limit under one still gives the nearest one");

console.log("a place from what a record holds");
eq(placeOf({ lat: 12.97, lng: 77.59 }), { lat: 12.97, lng: 77.59 }, "lat and lng");
eq(placeOf({ latitude: 12.97, longitude: 77.59 }), { lat: 12.97, lng: 77.59 }, "latitude and longitude");
eq(placeOf("{\"lat\":12.97,\"lng\":77.59}"), { lat: 12.97, lng: 77.59 }, "JSON text");
eq(placeOf([77.59, 12.97]), { lat: 12.97, lng: 77.59 }, "a [lng, lat] pair");
eq([placeOf(null), placeOf("nope"), placeOf({ lat: 200, lng: 0 }), placeOf({}), placeOf(7)], [null, null, null, null, null], "anything else is no place");

console.log("what a step's `nearest` means");
const duty = fleet.map((m) => ({ ...m, at: m.at }));
let w = whoIsNear({ entity: "Driver", from: "x", limit: 2 }, pickup, duty, now);
eq(w.userIds, ["u-near", "u-mid"], "the two nearest; the default window of two minutes keeps the quiet one out");
w = whoIsNear({ entity: "Driver", limit: 5, maxKm: 10 }, JSON.stringify(pickup), duty, now);
eq(w.userIds, ["u-near", "u-mid"], "a radius, and the place as JSON text");
w = whoIsNear({ entity: "Driver", maxKm: 5 }, { lat: 40, lng: 40 }, duty, now);
ok(w.userIds.length === 0 && w.notice === "no driver on duty is near", "nobody near says so");
ok(whoIsNear({ entity: "Driver" }, "not a place", duty, now).notice === "the place to look near is not a place", "a place that is not one says so");
ok(whoIsNear({ entity: "" }, pickup, duty, now).notice === "`nearest` names no entity to look for", "no entity says so");
eq(whoIsNear({ entity: "Driver", maxAgeSeconds: 1000 }, pickup, duty, now).userIds.includes("u-stale"), true, "a window set by the step is used: heard 600 s ago, window 1000 s, so still near");

console.log("the message for a phone");
ok(validExpoToken("ExponentPushToken[abc-123]") && validExpoToken("ExpoPushToken[x]"), "an Expo token is accepted");
ok(!validExpoToken("abc") && !validExpoToken("ExponentPushToken[]") && !validExpoToken(null) && !validExpoToken("ExponentPushToken[a b]"), "anything else is not");
const msgs = expoMessages(["ExponentPushToken[a]", "junk"], { title: "New ride", body: "₹240 · 2.1 km", link: "/", tag: "ride-1", ttl: 90 });
eq(msgs.length, 1, "a token that is not one is dropped");
eq({ to: msgs[0].to, title: msgs[0].title, body: msgs[0].body, ttl: msgs[0].ttl, priority: msgs[0].priority, data: msgs[0].data },
   { to: "ExponentPushToken[a]", title: "New ride", body: "₹240 · 2.1 km", ttl: 90, priority: "high", data: { link: "/", tag: "ride-1" } }, "the message as Expo gets it");
eq(expoMessages(["ExponentPushToken[a]"], { title: "x", link: "https://evil.example" })[0].data.link, null, "a link that leaves the app is not carried");

console.log("sending");
const calls: any[] = [];
const fakeFetch = (answer: (batch: any[]) => any, status = 200) => (async (url: string, init: any) => {
  const batch = JSON.parse(init.body);
  calls.push({ url, headers: init.headers, batch });
  return { ok: status < 400, status, json: async () => answer(batch) };
}) as unknown as typeof fetch;

let r = await sendExpo(["ExponentPushToken[a]", "ExponentPushToken[b]", "ExponentPushToken[a]"], { title: "New ride" },
  { fetch: fakeFetch((b) => ({ data: b.map((m: any) => (m.to.endsWith("[b]") ? { status: "error", message: "gone", details: { error: "DeviceNotRegistered" } } : { status: "ok", id: "t" })) })), env: {} });
eq({ sent: r.sent, dead: r.dead }, { sent: 1, dead: ["ExponentPushToken[b]"] }, "one accepted, one forgotten, a repeat sent once");
eq(calls[0].url, EXPO_SEND_URL, "to Expo's push service");
ok(!("Authorization" in calls[0].headers), "no access token unless the app has one");
await sendExpo(["ExponentPushToken[a]"], { title: "x" }, { fetch: fakeFetch(() => ({ data: [{ status: "ok" }] })), env: { EXPO_ACCESS_TOKEN: "secret" } });
eq(calls[1].headers.Authorization, "Bearer secret", "with the app's access token when it has one");

calls.length = 0;
const many = Array.from({ length: EXPO_BATCH + 20 }, (_, i) => `ExponentPushToken[t${i}]`);
r = await sendExpo(many, { title: "x" }, { fetch: fakeFetch((b) => ({ data: b.map(() => ({ status: "ok" })) })), env: {} });
eq({ sent: r.sent, requests: calls.length, sizes: calls.map((c) => c.batch.length) }, { sent: EXPO_BATCH + 20, requests: 2, sizes: [EXPO_BATCH, 20] }, "more than a hundred go in batches");

r = await sendExpo(["ExponentPushToken[a]"], { title: "x" }, { fetch: fakeFetch(() => ({}), 503), env: {} });
ok(r.sent === 0 && /503/.test(String(r.notice)), "Expo down: nothing sent, and it says why");
r = await sendExpo(["ExponentPushToken[a]"], { title: "x" }, { fetch: (async () => { throw new Error("offline"); }) as unknown as typeof fetch, env: {} });
ok(r.sent === 0 && /offline/.test(String(r.notice)), "no network: nothing sent, never thrown");
r = await sendExpo(["ExponentPushToken[a]"], { title: "x" }, { fetch: fakeFetch(() => ({ data: [{ status: "error", message: "MessageTooBig", details: { error: "MessageTooBig" } }] })), env: {} });
ok(r.sent === 0 && r.dead.length === 0 && /MessageTooBig/.test(String(r.notice)), "a refused alert is told, and its token is kept");
eq(await sendExpo([], { title: "x" }, { env: {} }), { sent: 0, dead: [] }, "nobody, nothing");

console.log("the live fleet remembers a driver nobody was watching");
const at0 = Date.now();
eq(fleetPublish("fleet:testdriver", "d1", "u1", { lat: 12.97, lng: 77.59, at: at0 }, { label: "A" }, at0), "ok", "the first driver reports in with no one watching the map");
eq(fleetSnapshot("fleet:testdriver", at0 + 1000).map((m) => m.id), ["d1"], "and is still on the map afterwards (the empty fleet was being forgotten before they were added)");
eq(fleetOnDuty("fleet:testdriver", at0 + 1000).map((m) => [m.id, m.who]), [["d1", "u1"]], "with the sign-in id of the phone that said so");
fleetPublish("fleet:testdriver", "d2", "u2", { lat: 12.98, lng: 77.6, at: at0 }, { label: "B" }, at0 + 500);
eq(fleetSnapshot("fleet:testdriver", at0 + 1000).map((m) => m.id).sort(), ["d1", "d2"], "a second one joins them");
eq(fleetSnapshot("fleet:testdriver", at0 + FLEET_TTL_MS + 100).map((m) => m.id), ["d2"], "someone quiet for two minutes drops off, the other stays");
fleetLeave("fleet:testdriver", "d2", "u2");
eq(fleetSnapshot("fleet:testdriver", at0 + 1000), [], "and one who goes offline is gone");

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log("\nall passed");
