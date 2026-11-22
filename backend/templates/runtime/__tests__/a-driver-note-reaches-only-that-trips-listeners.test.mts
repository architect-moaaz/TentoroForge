/**
 * The tracking mailbox: a note reaches the listeners of ITS trip only, a late
 * note never pulls the dot backwards, a stranger can't send for someone else's
 * trip, an impossible place is not a place, and ending the trip tells everyone.
 *
 * Runs the SHIPPED hub.ts.
 */
// The shared harness needs Node 22.15+ (module hooks); this hub needs none, so
// three tiny checks live here and the test runs on any Node 22.
let failed = 0;
const ok = (c: unknown, name: string) => { if (!c) { failed++; console.error("FAIL", name); } };
const eqJson = (a: unknown, b: unknown, name: string) => ok(JSON.stringify(a) === JSON.stringify(b), `${name} (got ${JSON.stringify(a)})`);
const done = (label: string) => { console.log(failed ? `${label}: ${failed} failed` : `${label}: all passed`); process.exit(failed ? 1 : 0); };

// hub.ts imports nothing, so it needs no resolver hooks.
const hub: any = await import("../tracking/hub.ts");

const heard1: any[] = [];
const heard2: any[] = [];
const stop1 = hub.listen("t1", (f: any) => heard1.push(f));
hub.listen("t2", (f: any) => heard2.push(f));

// The first sender is the driver, even though a customer was already listening.
eqJson(hub.publish("t1", "ann", { lat: 12.97, lng: 77.59, at: 100 }), "ok", "the driver's note is taken");
eqJson(heard1.length, 1, "the trip's listener hears it at once");
eqJson(heard2.length, 0, "another trip's listener hears nothing");

eqJson(hub.publish("t1", "ann", { lat: 12.0, lng: 77.0, at: 50 }), "old", "a late note is ignored");
eqJson(hub.latest("t1").lat, 12.97, "the dot did not go backwards");
eqJson(heard1.length, 1, "and nobody was told about it");

eqJson(hub.publish("t1", "bob", { lat: 1, lng: 1, at: 200 }), "not-your-trip", "a stranger can't send for this trip");
eqJson(heard1.length, 1, "and nothing is heard from them");

ok(hub.validPosition(12.97, 77.59), "a real place");
ok(!hub.validPosition(500, 0), "latitude 500 is no place");
ok(!hub.validPosition(0, 181), "longitude 181 is no place");
ok(!hub.validPosition(NaN, 0), "NaN is no place");
ok(!hub.validPosition("12", "77"), "words are no place");

// Someone who opens late still sees where the driver is.
eqJson(hub.latest("t1").at, 100, "a late opener gets the newest note");

ok(!hub.finish("t1", "bob"), "only the driver ends the trip");
ok(hub.finish("t1", "ann"), "the driver ends it");
eqJson(heard1.at(-1), { done: true }, "listeners are told it ended");
eqJson(hub.latest("t1"), undefined, "the spot is forgotten");

// A listener that leaves before any driver is gone leaves nothing behind.
const stop3 = hub.listen("t3", () => {});
stop3();
eqJson(hub.latest("t3"), undefined, "an empty trip leaves nothing");
stop1();

done("tracking hub");
