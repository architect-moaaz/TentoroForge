/**
 * Standalone tests for the self-written 5-field cron matcher
 * (events/cron.ts) — the R2 scheduler's due-ness authority.
 *
 * Run (Node 22+ with built-in type stripping):
 *   cd backend/templates/runtime && \
 *   node --experimental-strip-types __tests__/event-cron.test.mts
 * Exits 0 on pass, 1 on any failure. No package.json, no vitest —
 * matches the standalone-inline pattern established by
 * decision.test.mts / build-where.test.mts.
 */

import { parseCronField, isValidCron, cronMatches, isDue } from "../events/cron.ts";

let passed = 0;
let failed = 0;

function assertEq<T>(actual: T, expected: T, name: string): void {
  const ok =
    actual === expected || JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed++;
    console.log(`  ✓ ${name}`);
  } else {
    failed++;
    console.log(`  ✗ ${name}`);
    console.log(`      expected: ${JSON.stringify(expected)}`);
    console.log(`      actual:   ${JSON.stringify(actual)}`);
  }
}

// UTC date helper: y, m(1-12), d, hh, mm
function utc(y: number, m: number, d: number, hh: number, mm: number): Date {
  return new Date(Date.UTC(y, m - 1, d, hh, mm, 0, 0));
}

// ── parseCronField ──────────────────────────────────────────────────

console.log("parseCronField:");
assertEq(parseCronField("*", 0, 59), "*", '"*" is any');
assertEq(parseCronField("5", 0, 59), new Set([5]), "exact number");
assertEq(parseCronField("1,3,5", 0, 59), new Set([1, 3, 5]), "comma list");
assertEq(parseCronField("10-12", 0, 59), new Set([10, 11, 12]), "range");
assertEq(
  parseCronField("*/15", 0, 59),
  new Set([0, 15, 30, 45]),
  "*/15 step from field minimum",
);
assertEq(parseCronField("10-20/5", 0, 59), new Set([10, 15, 20]), "range with step");
assertEq(parseCronField("60", 0, 59), null, "out-of-bounds number rejected");
assertEq(parseCronField("banana", 0, 59), null, "garbage rejected");
assertEq(parseCronField("*/0", 0, 59), null, "zero step rejected");
assertEq(parseCronField("9-3", 0, 59), null, "inverted range rejected");

// ── isValidCron ─────────────────────────────────────────────────────

console.log("isValidCron:");
assertEq(isValidCron("0 9 * * 1"), true, "classic weekly");
assertEq(isValidCron("*/5 * * * *"), true, "every 5 minutes");
assertEq(isValidCron("0 9 * *"), false, "4 fields rejected");
assertEq(isValidCron("0 9 * * * *"), false, "6 fields rejected");
assertEq(isValidCron("daily"), false, "prose rejected");
assertEq(isValidCron(""), false, "empty rejected");

// ── cronMatches ─────────────────────────────────────────────────────

console.log("cronMatches:");
// 2026-08-17 is a Monday.
assertEq(cronMatches("0 9 * * 1", utc(2026, 8, 17, 9, 0)), true, "Mon 09:00 matches weekly Mon");
assertEq(cronMatches("0 9 * * 1", utc(2026, 8, 18, 9, 0)), false, "Tue 09:00 does not");
assertEq(cronMatches("0 9 * * 1", utc(2026, 8, 17, 9, 1)), false, "09:01 does not");
assertEq(cronMatches("*/15 * * * *", utc(2026, 8, 17, 3, 30)), true, "*/15 at :30");
assertEq(cronMatches("*/15 * * * *", utc(2026, 8, 17, 3, 31)), false, "*/15 at :31");
assertEq(cronMatches("30 6 1 * *", utc(2026, 9, 1, 6, 30)), true, "monthly on the 1st");
assertEq(cronMatches("30 6 1 * *", utc(2026, 9, 2, 6, 30)), false, "not on the 2nd");
assertEq(cronMatches("0 0 * 8 *", utc(2026, 8, 17, 0, 0)), true, "month field (August)");
assertEq(cronMatches("0 0 * 7 *", utc(2026, 8, 17, 0, 0)), false, "month field (not July)");
// 2026-08-23 is a Sunday — 7 ≡ 0.
assertEq(cronMatches("0 0 * * 7", utc(2026, 8, 23, 0, 0)), true, "dow 7 matches Sunday");
assertEq(cronMatches("0 0 * * 0", utc(2026, 8, 23, 0, 0)), true, "dow 0 matches Sunday");
// Vixie OR rule: both dom and dow restricted → either may match.
assertEq(
  cronMatches("0 0 17 * 1", utc(2026, 8, 17, 0, 0)),
  true,
  "dom+dow both restricted: dom match suffices (17th, a Monday anyway)",
);
assertEq(
  cronMatches("0 0 25 * 2", utc(2026, 8, 18, 0, 0)),
  true,
  "dom+dow both restricted: dow match suffices (Tue, not the 25th)",
);
assertEq(
  cronMatches("0 0 25 * 5", utc(2026, 8, 18, 0, 0)),
  false,
  "dom+dow both restricted: neither matches",
);
assertEq(cronMatches("bad cron", utc(2026, 8, 17, 0, 0)), false, "invalid expr never matches");

// ── isDue — fire-once-per-window semantics ──────────────────────────

console.log("isDue:");
const nowMon0905 = utc(2026, 8, 17, 9, 5);
assertEq(
  isDue("0 9 * * 1", utc(2026, 8, 17, 8, 0), nowMon0905),
  true,
  "due: 09:00 window passed since last run at 08:00",
);
assertEq(
  isDue("0 9 * * 1", utc(2026, 8, 17, 9, 0), nowMon0905),
  false,
  "not due again: already fired in the 09:00 minute",
);
assertEq(
  isDue("0 9 * * 1", utc(2026, 8, 17, 9, 2), nowMon0905),
  false,
  "not due: lastRun after the matching minute",
);
assertEq(
  isDue("*/15 * * * *", utc(2026, 8, 17, 8, 50), utc(2026, 8, 17, 9, 1)),
  true,
  "*/15 due (09:00 in window)",
);
assertEq(
  isDue("*/15 * * * *", utc(2026, 8, 17, 9, 0), utc(2026, 8, 17, 9, 10)),
  false,
  "*/15 not due until :15",
);
// Missed window recovered within lookback: daily 09:00, last ran yesterday
// 09:00, sweeper only comes back at 11:23 today.
assertEq(
  isDue("0 9 * * *", utc(2026, 8, 16, 9, 0), utc(2026, 8, 17, 11, 23)),
  true,
  "missed daily window swept late still fires once",
);
// Never-run schedule: short lookback so a fresh deploy doesn't replay a day.
assertEq(
  isDue("0 9 * * *", null, utc(2026, 8, 17, 9, 30)),
  true,
  "first run fires when due minute is within the short lookback",
);
assertEq(
  isDue("0 9 * * *", null, utc(2026, 8, 17, 15, 0)),
  false,
  "first run does NOT replay a due minute hours in the past",
);
assertEq(isDue("not a cron", null, nowMon0905), false, "invalid cron never due");

// ── result ──────────────────────────────────────────────────────────

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
