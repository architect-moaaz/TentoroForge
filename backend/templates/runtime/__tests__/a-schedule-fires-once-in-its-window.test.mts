/**
 * A schedule fires once in its window, whatever zone the server is in.
 *
 * forge_schedules.last_run_at is a `timestamp` WITHOUT time zone: the
 * scheduler writes `now.toISOString()` into it and Postgres keeps the UTC wall
 * time, handing it back as text ("2026-11-18 10:48:05.082"). Read with
 * `new Date(text)`, that text is the SERVER's local time — on a machine in
 * India every last run looked 5½ hours old, every schedule was always due, and
 * the local DITANS copy ran a 15-minute job 270 times an hour (2026-11-18).
 *
 * Runs the SHIPPED events/scheduler.ts and events/cron.ts with the process in
 * Asia/Kolkata, a stub database that stores and returns the column as Postgres
 * does, and a clock that ticks every minute.
 */
process.env.TZ = "Asia/Kolkata";
import { installHarness, eqJson, ok, done } from "./_harness.mts";

(globalThis as any).__LAST__ = new Map<string, string>();
(globalThis as any).__FIRED__ = [] as string[];
(globalThis as any).__WFS__ = [];
installHarness({ stubs: {
  "drizzle-orm": `
    const tag = (strings, ...values) => ({ strings: [...strings], values, text: strings.join("?") });
    export const sql = tag;`,
  "@/db": `
    // AS POSTGRES DOES: an ISO instant cast to timestamp keeps its UTC wall time
    // and comes back as text with no zone.
    const asTimestamp = (iso) => iso.replace("T", " ").replace(/Z$/, "");
    export const db = {
      async execute(q) {
        if (q.text.includes("SELECT last_run_at, enabled FROM forge_schedules")) {
          const at = globalThis.__LAST__.get(q.values[0]);
          return at ? [{ last_run_at: at, enabled: true }] : [];
        }
        if (q.text.includes("INSERT INTO forge_schedules")) {
          globalThis.__LAST__.set(q.values[0], asTimestamp(q.values[2]));
          return [];
        }
        return [];
      },
    };`,
  "@/lib/workflows": `
    export async function listWorkflows() { return globalThis.__WFS__; }
    export async function triggerWorkflow(id) { globalThis.__FIRED__.push(id); return {}; }`,
} });

const cron: any = await import("../events/cron.ts");
const scheduler: any = await import("../events/scheduler.ts");

console.log("a timestamp written as UTC is read as UTC");
eqJson(new Date(2026, 10, 18).getTimezoneOffset(), -330, "the process runs in India (UTC+5:30)");
eqJson(cron.fromDbTime("2026-11-18 10:48:05.082")?.toISOString(), "2026-11-18T10:48:05.082Z", "text with no zone");
eqJson(cron.fromDbTime("2026-11-18 10:48:05")?.toISOString(), "2026-11-18T10:48:05.000Z", "without milliseconds");
eqJson(cron.fromDbTime("2026-11-18 10:48:05+00")?.toISOString(), "2026-11-18T10:48:05.000Z", "timestamptz text keeps its zone");
eqJson(cron.fromDbTime("2026-11-18T16:18:05+05:30")?.toISOString(), "2026-11-18T10:48:05.000Z", "an offset is honoured");
eqJson(cron.fromDbTime("2026-11-18")?.toISOString(), "2026-11-18T00:00:00.000Z", "a bare date");
const d = new Date("2026-11-18T10:48:05Z");
ok(cron.fromDbTime(d) === d, "a Date is taken as it is");
eqJson([cron.fromDbTime(null), cron.fromDbTime(""), cron.fromDbTime("not a time")], [null, null, null], "nothing, or nonsense, is no time");

/** Tick every minute from `from` for `minutes`; how many times did each workflow fire? */
async function run(from: string, minutes: number): Promise<Record<string, number>> {
  (globalThis as any).__FIRED__ = [];
  const start = new Date(from).getTime();
  for (let m = 0; m < minutes; m++) await scheduler.runDueSchedules(new Date(start + m * 60_000));
  const counts: Record<string, number> = {};
  for (const id of (globalThis as any).__FIRED__) counts[id] = (counts[id] ?? 0) + 1;
  return counts;
}

console.log("a clock ticking every minute");
(globalThis as any).__WFS__ = [
  { id: "close-filled-jobs", trigger: { kind: "schedule", cron: "*/15 * * * *", timezone: "Asia/Dubai" } },
  { id: "send-90-day-profile-check", trigger: { kind: "schedule", cron: "0 9 * * *", timezone: "Asia/Dubai" } },
  { id: "weekday-reminders", trigger: { kind: "schedule", cron: "0 7-18 * * 1-5", timezone: "Asia/Dubai" } },
];
// Wednesday 18 Nov 2026, 00:00 UTC (04:00 in Dubai) for a whole day.
const day = await run("2026-11-18T00:00:00Z", 24 * 60);
eqJson(day["close-filled-jobs"], 96, "every 15 minutes: 96 times a day, 4 an hour");
eqJson(day["send-90-day-profile-check"], 1, "once a day at 09:00 Dubai");
eqJson(day["weekday-reminders"], 12, "hourly 07:00–18:00 Dubai on a weekday: 12");
const hour = await run("2026-11-19T00:00:00Z", 60);
eqJson(hour["close-filled-jobs"], 4, "and in any one hour, 4");
eqJson(hour["send-90-day-profile-check"] ?? 0, 0, "the daily one not again before its time");

done("schedule fires once in its window");
