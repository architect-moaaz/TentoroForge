/**
 * Who may do what on a tracked job. The person the record names as being on the
 * move may share a position; a customer who can merely open the record may not;
 * and nobody shares one once the job is over.
 *
 * Runs the SHIPPED rules.ts (it imports nothing, so no resolver hooks are needed
 * and this runs on any Node 22).
 */
let failed = 0;
const ok = (c: unknown, name: string) => { if (!c) { failed++; console.error("FAIL", name); } };
const eq = (a: unknown, b: unknown, name: string) => ok(JSON.stringify(a) === JSON.stringify(b), `${name} (got ${JSON.stringify(a)})`);

const { moverId, finished, mayShare, tripKey }: any = await import("../tracking/rules.ts");

// The person on the move is whoever the record names, under whatever role it uses.
eq(moverId({ id: "o1", customerId: "c1", driverId: "d1" }), "d1", "driverId");
eq(moverId({ customerId: "c1", courier_id: "k1" }), "k1", "courier_id");
eq(moverId({ technicianId: "t1" }), "t1", "technicianId");
eq(moverId({ assignee: "a1" }), "a1", "assignee");
eq(moverId({ customerId: "c1", ownerId: "c1" }), null, "a job that names nobody on the move");
eq(moverId({ driverId: null }), null, "an empty driver field names nobody");
eq(moverId(null), null, "no job");

// Only that person may share.
const job = { customerId: "c1", driverId: "d1", status: "on_the_way" };
ok(mayShare(job, "d1"), "the driver may share");
ok(!mayShare(job, "c1"), "the customer, who can open it, may not");
ok(!mayShare(job, "x9"), "a stranger may not");
ok(!mayShare({ customerId: "c1" }, "c1"), "a job naming nobody lets nobody share (no squatting)");
ok(!mayShare(job, null), "signed out may not");

// Never after the job.
for (const status of ["delivered", "Delivered", "cancelled", "canceled", "completed", "done", "closed", "dropped off", "arrived"])
  ok(finished({ status }), `${status} is over`);
for (const status of ["pending", "accepted", "on the way", "picked_up", "in transit", "driver assigned"])
  ok(!finished({ status }), `${status} is under way`);
ok(!finished({}), "a job with no status is not over");
ok(!finished(null), "no job is not over");

eq(tripKey("Order", "abc"), "order:abc", "the mailbox key names the kind of record");
ok(tripKey("Order", "1") !== tripKey("Ride", "1"), "two kinds of record never share a mailbox");

console.log(failed ? `access rules: ${failed} failed` : "access rules: all passed");
process.exit(failed ? 1 : 0);
