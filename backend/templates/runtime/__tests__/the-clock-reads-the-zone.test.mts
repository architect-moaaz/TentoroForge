/**
 * A schedule's cron is read in its own timezone: 09:00 in Dubai is 05:00
 * UTC. Pure module — no stubs.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();

const cron: any = await import("../events/cron.ts");
const fiveUtc = new Date("2026-10-12T05:00:00Z");
ok(cron.cronMatches("0 9 * * *", fiveUtc, "Asia/Dubai"), "09:00 in Dubai matches at 05:00 UTC");
ok(!cron.cronMatches("0 9 * * *", fiveUtc), "and not in UTC");
ok(cron.cronMatches("0 5 * * 1", fiveUtc), "Monday 05:00 UTC in UTC");
eqJson(cron.clockParts(fiveUtc, "Asia/Dubai"), { minute: 0, hour: 9, dom: 12, month: 10, dow: 1 }, "the clock parts in the zone");
ok(cron.isDue("0 9 * * *", new Date("2026-10-11T05:00:00Z"), new Date("2026-10-12T05:03:00Z"), "Asia/Dubai"), "due once in its window");
ok(!cron.isDue("0 9 * * *", new Date("2026-10-12T05:00:00Z"), new Date("2026-10-12T05:03:00Z"), "Asia/Dubai"), "and not twice");
const trig: any = await import("../events/triggers.ts");
eqJson(trig.getTriggerContract({ trigger: { kind: "schedule", cron: "0 9 * * *", timezone: "Asia/Dubai", enabled: false } }),
       { kind: "schedule", cron: "0 9 * * *", timezone: "Asia/Dubai", enabled: false }, "the contract carries zone and pause");
done("the clock reads the zone");
