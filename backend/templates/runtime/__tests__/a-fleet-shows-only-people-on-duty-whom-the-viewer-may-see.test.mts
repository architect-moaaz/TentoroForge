/**
 * The fleet: many people on the move at once (drivers online, no job yet).
 * A person may be on the map only if the record is theirs and they are cleared
 * and on duty; they leave it when they go off duty or go quiet; and one person
 * can never speak for another's record.
 *
 * Runs the SHIPPED rules.ts and hub.ts (neither pulls in the app's data layer).
 */
let failed = 0;
const ok = (c: unknown, name: string) => { if (!c) { failed++; console.error("FAIL", name); } };
const eq = (a: unknown, b: unknown, name: string) => ok(JSON.stringify(a) === JSON.stringify(b), `${name} (got ${JSON.stringify(a)})`);

const { isSelf, whyNotOnDuty, fleetLabel, fleetKind, fleetKey }: any = await import("../tracking/rules.ts");
const hub: any = await import("../tracking/hub.ts");

// --- whose record is it ---------------------------------------------------
ok(isSelf({ id: "u1" }, "u1"), "a record whose id is the person");
ok(isSelf({ id: "d1", userId: "u1" }, "u1"), "a record naming the person by userId");
ok(isSelf({ id: "d1", account_id: "u1" }, "u1"), "account_id");
ok(isSelf({ id: "d1", driverId: "u1" }, "u1"), "a record naming them as the mover");
ok(!isSelf({ id: "d1", userId: "u2" }, "u1"), "someone else's record");
ok(!isSelf({ id: "d1" }, null), "signed out");
ok(!isSelf(null, "u1"), "no record");

// --- cleared and on duty --------------------------------------------------
eq(whyNotOnDuty({ verification_status: "approved", availability_status: "online" }), null, "approved and online");
eq(whyNotOnDuty({}), null, "a record that says nothing is not blocked");
ok(whyNotOnDuty({ verification_status: "pending" }), "pending verification may not go online");
ok(whyNotOnDuty({ verification_status: "pending_verification" }), "pending_verification");
ok(whyNotOnDuty({ verificationStatus: "Suspended" }), "camelCase field names count too");
ok(whyNotOnDuty({ availabilityStatus: "OFFLINE" }), "availabilityStatus offline");
eq(whyNotOnDuty({ verificationStatus: "approved", availabilityStatus: "online" }), null, "camelCase approved and online");
ok(whyNotOnDuty({ verification_status: "rejected" }), "rejected");
ok(whyNotOnDuty({ verification_status: "suspended" }), "suspended");
ok(whyNotOnDuty({ verification_status: "approved", availability_status: "offline" }), "offline says go online first");
ok(whyNotOnDuty({ verification_status: "approved", is_online: false }), "is_online false");
ok(whyNotOnDuty({ status: "suspended" }), "status suspended");
eq(whyNotOnDuty({ verification_status: "approved", is_online: true }), null, "is_online true");
ok(whyNotOnDuty(null), "no record");

// --- what the pin says ----------------------------------------------------
eq(fleetLabel({ name: " Asha " }), "Asha", "name");
eq(fleetLabel({ id: "x" }), undefined, "no name");
eq(fleetKind({ vehicle_type: "Sedan" }), "Sedan", "vehicle_type");
eq(fleetKind({ id: "x" }), undefined, "no kind");
ok(fleetKey("Driver") === fleetKey("driver") && fleetKey("Driver") !== fleetKey("Courier"), "one fleet per kind of record");

// --- the mailbox ----------------------------------------------------------
const K = "fleet:test";
const at = (n: number) => ({ lat: 12.9 + n / 1000, lng: 77.5, at: 1000 + n });
const heard: any[] = [];
const stop = hub.fleetListen(K, (f: any) => heard.push(f));

eq(hub.fleetPublish(K, "d1", "u1", at(1), { label: "Asha", kind: "Sedan" }, 5_000), "ok", "first note");
eq(hub.fleetPublish(K, "d1", "u2", at(2), {}, 5_000), "not-your-trip", "someone else cannot speak for d1");
eq(hub.fleetPublish(K, "d1", "u1", at(0), {}, 5_000), "old", "an older note is ignored");
eq(hub.fleetPublish(K, "d2", "u2", at(1), { label: "Ravi", kind: "Bike" }, 5_000), "ok", "a second driver");
eq(heard.map((f) => f.id), ["d1", "d2"], "listeners heard both, and not the refused ones");
eq(hub.fleetSnapshot(K, 5_000).map((m: any) => m.id).sort(), ["d1", "d2"], "the snapshot has both");
eq(hub.fleetSnapshot(K, 5_000).find((m: any) => m.id === "d1").label, "Asha", "the label travels");

// someone who opens late sees everyone at once
const snapshot = hub.fleetSnapshot(K, 5_000);
ok(snapshot.length === 2, "a late viewer sees the whole fleet");

// going off duty
ok(!hub.fleetLeave(K, "d1", "u2"), "another person cannot take d1 off the map");
ok(hub.fleetLeave(K, "d1", "u1"), "the owner goes off duty");
eq(heard.at(-1), { gone: "d1" }, "listeners are told");
eq(hub.fleetSnapshot(K, 5_000).map((m: any) => m.id), ["d2"], "only d2 remains");

// the server takes someone off the map because their RECORD says off duty (Go offline is a workflow, not this line)
hub.fleetPublish(K, "d3", "u3", at(5), { label: "Mina" }, 6_000);
ok(hub.fleetSnapshot(K, 6_000).some((m: any) => m.id === "d3"), "d3 is on the map");
ok(hub.fleetDrop(K, "d3"), "the server drops d3 by record");
eq(heard.at(-1), { gone: "d3" }, "listeners are told d3 is gone");
ok(!hub.fleetDrop(K, "d3"), "dropping someone not on the map is a no-op");

// going quiet: a dead phone is not a driver still waiting for work
eq(hub.fleetSnapshot(K, 5_000 + hub.FLEET_TTL_MS + 1), [], "after two quiet minutes nobody is shown");
eq(heard.at(-1), { gone: "d2" }, "and the viewers are told");

stop();
eq(hub.fleetSnapshot(K), [], "an unwatched empty fleet is forgotten");

console.log(failed ? `fleet: ${failed} failed` : "fleet: all passed");
process.exit(failed ? 1 : 0);
