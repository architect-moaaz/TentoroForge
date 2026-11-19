/**
 * A month on is the same day next month, not nothing. `duration("P1M")` read
 * as no time at all, so `$today + duration("P1M")` was today and a DITANS
 * subscription's first period ended the day it began (FLOW-071, 2026-11-18).
 * Years and months are calendar arithmetic, clamped at a short month's end;
 * a duration that is not one is refused by the engine and by the check.
 * Runs the SHIPPED feel-lite.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();

const feel: any = await import("../feel-lite/index.ts");
const run = (expr: string, data: Record<string, unknown> = {}) => feel.evaluateExpression(expr, data);

// $today, a month and a year on — worked out here without the engine.
const today: string = run("$today");
const [y, m, d] = today.split("-").map(Number);
const ymd = (yy: number, mm: number, dd: number) => {
  const last = new Date(Date.UTC(yy, mm, 0)).getUTCDate(); // mm is 1-based: day 0 of the next month
  return `${yy}-${String(mm).padStart(2, "0")}-${String(Math.min(dd, last)).padStart(2, "0")}`;
};
const nextMonth = m === 12 ? ymd(y + 1, 1, d) : ymd(y, m + 1, d);
eqJson(run('$today + duration("P1M")'), nextMonth, "$today + P1M is the same day next month");
ok(run('$today + duration("P1M")') !== today, "$today + P1M is not today");
eqJson(run('$today + duration("P1Y")'), ymd(y + 1, m, d), "$today + P1Y is the same day next year");

// Fixed dates: months first, then days.
eqJson(run('d + duration("P1M")', { d: "2026-11-18" }), "2026-12-18", "18 Nov + P1M = 18 Dec");
eqJson(run('d + duration("P1M")', { d: "2026-12-15" }), "2027-01-15", "a month on crosses the year");
eqJson(run('d + duration("P1Y")', { d: "2026-11-18" }), "2027-11-18", "18 Nov 2026 + P1Y = 18 Nov 2027");
eqJson(run('d + duration("P1Y2M10D")', { d: "2026-01-15" }), "2027-03-25", "15 Jan 2026 + P1Y2M10D = 25 Mar 2027");
eqJson(run('d + duration("P1M")', { d: "2026-01-31" }), "2026-02-28", "31 Jan + P1M = 28 Feb");
eqJson(run('d + duration("P1M")', { d: "2028-01-31" }), "2028-02-29", "31 Jan in a leap year + P1M = 29 Feb");
eqJson(run('d + duration("P1Y")', { d: "2028-02-29" }), "2029-02-28", "29 Feb + P1Y = 28 Feb");
eqJson(run('d - duration("P1M")', { d: "2026-03-31" }), "2026-02-28", "31 Mar - P1M = 28 Feb");
eqJson(run('d + duration("-P1M")', { d: "2026-03-15" }), "2026-02-15", "a negative month goes back");
eqJson(run('duration("P1M") + d', { d: "2026-11-18" }), "2026-12-18", "a duration first adds the same");
eqJson(run('d + duration("P1M") * 3', { d: "2026-11-30" }), "2027-02-28", "three months on, clamped");
eqJson(run('d + (duration("P1M") + duration("P10D"))', { d: "2026-01-31" }), "2026-03-10", "P1M + P10D: the month, then the days");
eqJson(run('ts + duration("P1M")', { ts: "2026-01-31T09:30:00.000Z" }), "2026-02-28T09:30:00.000Z", "a moment keeps its time of day");
eqJson(run('d + duration("P2W")', { d: "2026-11-18" }), "2026-12-02", "weeks are seven days");

// Days and clock time are still milliseconds: what already worked still does.
eqJson(run('duration("P1D")'), 86400000, "P1D is still 86 400 000 ms");
eqJson(run('d + duration("P30D")', { d: "2026-11-18" }), "2026-12-18", "P30D is still thirty days");
eqJson(run('(date("2026-10-13") - date("2026-10-12")) = duration("P1D")'), true, "a day between is P1D");
eqJson(run('string(duration("P1Y2M10D"))'), "P1Y2M10D", "a calendar duration reads as ISO text");
eqJson(run('duration(x)', { x: null }), null, "duration of nothing is nothing");

// A duration that is not one is refused, never 0.
for (const bad of ["P1X", "1M", "P", "PT", "P1DT", "month", "30"]) {
  let threw: unknown = null;
  try { run(`d + duration("${bad}")`, { d: "2026-11-18" }); } catch (e) { threw = e; }
  ok(threw instanceof Error && /Not a duration/.test((threw as Error).message), `the engine refuses duration("${bad}")`);
  const v = feel.validate(`$today + duration("${bad}")`);
  ok(v.valid === false && v.issues.some((i: any) => i.severity === "error" && /Not a duration/.test(i.message)),
    `the check refuses duration("${bad}")`);
}
for (const good of ["P1M", "P1Y", "P1Y2M10D", "P30D", "PT2H", "-P1M", "P2W", "PT1.5S"]) {
  ok(feel.validate(`$today + duration("${good}")`).valid, `the check accepts duration("${good}")`);
}
ok(feel.validate("$today + duration(term)").valid, "a duration read from a field is checked when it runs");

done("calendar duration");
