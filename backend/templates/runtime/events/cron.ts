/**
 * Minimal 5-field cron matcher — no npm dependency, serverless-safe.
 *
 * Grammar per field (minute, hour, day-of-month, month, day-of-week):
 *   "*"          any value
 *   "*" + "/n"   every n, from the field's minimum (the star-slash-n step
 *                form — spelled out here because a literal star-slash in
 *                this comment would close it)
 *   a,b,c        comma list
 *   a-b          inclusive range
 *   a-b/n        range with step
 *   n            exact number
 * Day-of-week accepts 0-7 (7 ≡ 0 ≡ Sunday). All evaluation is in UTC —
 * Vercel cron fires in UTC, so authored schedules line up 1:1.
 *
 * Pure module: no imports, standalone-testable with
 * `node --experimental-strip-types __tests__/event-cron.test.mts`.
 */

/** Parse one cron field into the set of matching values, or "*" for any. */
export function parseCronField(
  field: string,
  min: number,
  max: number,
): Set<number> | "*" | null {
  const f = field.trim();
  if (f === "*") return "*";
  const out = new Set<number>();
  for (const part of f.split(",")) {
    const p = part.trim();
    if (!p) return null;
    // step: */n or a-b/n
    const stepMatch = p.match(/^(\*|\d+-\d+)\/(\d+)$/);
    if (stepMatch) {
      const step = Number(stepMatch[2]);
      if (!step || step < 1) return null;
      let lo = min;
      let hi = max;
      if (stepMatch[1] !== "*") {
        const [a, b] = stepMatch[1].split("-").map(Number);
        lo = a;
        hi = b;
      }
      if (lo < min || hi > max || lo > hi) return null;
      for (let v = lo; v <= hi; v += step) out.add(v);
      continue;
    }
    // range: a-b
    const rangeMatch = p.match(/^(\d+)-(\d+)$/);
    if (rangeMatch) {
      const a = Number(rangeMatch[1]);
      const b = Number(rangeMatch[2]);
      if (a < min || b > max || a > b) return null;
      for (let v = a; v <= b; v++) out.add(v);
      continue;
    }
    // exact number
    if (!/^\d+$/.test(p)) return null;
    const n = Number(p);
    if (n < min || n > max) return null;
    out.add(n);
  }
  return out;
}

/** True when `expr` is a syntactically valid 5-field cron expression. */
export function isValidCron(expr: string): boolean {
  const parts = String(expr ?? "").trim().split(/\s+/);
  if (parts.length !== 5) return false;
  const bounds: Array<[number, number]> = [
    [0, 59], // minute
    [0, 23], // hour
    [1, 31], // day of month
    [1, 12], // month
    [0, 7], // day of week (7 ≡ 0)
  ];
  return parts.every((p, i) => parseCronField(p, bounds[i][0], bounds[i][1]) !== null);
}

/**
 * Does `expr` match the given UTC minute?
 *
 * Standard (vixie) day semantics: when BOTH day-of-month and day-of-week
 * are restricted, the day matches if EITHER matches; when only one is
 * restricted it alone governs.
 */
export function cronMatches(expr: string, date: Date): boolean {
  const parts = String(expr ?? "").trim().split(/\s+/);
  if (parts.length !== 5) return false;

  const minute = parseCronField(parts[0], 0, 59);
  const hour = parseCronField(parts[1], 0, 23);
  const dom = parseCronField(parts[2], 1, 31);
  const mon = parseCronField(parts[3], 1, 12);
  const dow = parseCronField(parts[4], 0, 7);
  if (!minute || !hour || !dom || !mon || !dow) return false;

  const inSet = (set: Set<number> | "*", v: number): boolean =>
    set === "*" || set.has(v);

  if (!inSet(minute, date.getUTCMinutes())) return false;
  if (!inSet(hour, date.getUTCHours())) return false;
  if (!inSet(mon, date.getUTCMonth() + 1)) return false;

  // 7 ≡ 0 ≡ Sunday: normalise a set containing 7 to also contain 0.
  const day = date.getUTCDay();
  const dowMatch =
    dow === "*" || dow.has(day) || (day === 0 && dow.has(7));
  const domMatch = inSet(dom, date.getUTCDate());
  if (dom !== "*" && dow !== "*") return domMatch || dowMatch;
  if (dom !== "*") return domMatch;
  if (dow !== "*") return dowMatch;
  return true;
}

// How far back a sweep will look for a missed firing. Covers a daily
// schedule even when the cron pinger was down for a whole day.
const _LOOKBACK_MS = 26 * 60 * 60 * 1000;
// A schedule that has NEVER run only looks back one sweep-ish window so a
// fresh deploy doesn't replay a day of "missed" firings.
const _FIRST_RUN_LOOKBACK_MS = 61 * 60 * 1000;
const _MINUTE_MS = 60 * 1000;

/**
 * Should the schedule fire now? True when any minute in
 * (lastRunAt, now] — bounded by the lookback window — matches `expr`,
 * so each due window fires exactly once no matter how often (or rarely)
 * the sweeper is invoked.
 */
export function isDue(expr: string, lastRunAt: Date | null, now: Date): boolean {
  if (!isValidCron(expr)) return false;
  const nowFloor = Math.floor(now.getTime() / _MINUTE_MS) * _MINUTE_MS;
  const lookback = lastRunAt ? _LOOKBACK_MS : _FIRST_RUN_LOOKBACK_MS;
  let start = nowFloor - lookback;
  if (lastRunAt) {
    const lastFloor = Math.floor(lastRunAt.getTime() / _MINUTE_MS) * _MINUTE_MS;
    // strictly AFTER the minute we last fired in
    start = Math.max(start, lastFloor + _MINUTE_MS);
  }
  for (let t = start; t <= nowFloor; t += _MINUTE_MS) {
    if (cronMatches(expr, new Date(t))) return true;
  }
  return false;
}
