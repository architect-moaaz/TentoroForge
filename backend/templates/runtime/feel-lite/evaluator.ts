/** FEEL-lite AST evaluator — walks the AST and evaluates against a context. */

import type { ASTNode } from "./ast";

export type Context = Record<string, unknown>;

/** Built-in functions available in FEEL-lite expressions. */
const BUILT_IN_FUNCTIONS: Record<string, (...args: unknown[]) => unknown> = {
  sum: (...args: unknown[]) => {
    const nums = flattenNumbers(args);
    return nums.reduce((a, b) => a + b, 0);
  },
  count: (...args: unknown[]) => {
    // NOTHING COUNTS AS NONE. `count(x)` of a missing value was 1 — the one
    // argument it was handed — so a duplicate check over a list that was not
    // there always found a duplicate (F&B, 2026-10-01).
    if (args.length === 1 && args[0] == null) return 0;
    const list = args.length === 1 && Array.isArray(args[0]) ? args[0] : args;
    return list.length;
  },
  min: (...args: unknown[]) => {
    const nums = flattenNumbers(args);
    return nums.length > 0 ? Math.min(...nums) : null;
  },
  max: (...args: unknown[]) => {
    const nums = flattenNumbers(args);
    return nums.length > 0 ? Math.max(...nums) : null;
  },
  avg: (...args: unknown[]) => {
    const nums = flattenNumbers(args);
    return nums.length > 0 ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
  },
  abs: (x: unknown) => Math.abs(toNumber(x)),
  floor: (x: unknown) => Math.floor(toNumber(x)),
  ceiling: (x: unknown) => Math.ceil(toNumber(x)),
  round: (x: unknown, scale?: unknown) => {
    const n = toNumber(x);
    const s = scale !== undefined ? toNumber(scale) : 0;
    const factor = Math.pow(10, s);
    return Math.round(n * factor) / factor;
  },
  contains: (str: unknown, sub: unknown) => String(str).includes(String(sub)),
  "starts with": (str: unknown, prefix: unknown) =>
    String(str).startsWith(String(prefix)),
  "ends with": (str: unknown, suffix: unknown) =>
    String(str).endsWith(String(suffix)),
  matches: (str: unknown, pattern: unknown) => {
    try {
      return new RegExp(String(pattern)).test(String(str));
    } catch {
      return false;
    }
  },
  string: (x: unknown) => String(x ?? ""),
  "string length": (x: unknown) => (x == null ? 0 : String(x).length),
  number: (x: unknown) => {
    const n = Number(x);
    return isNaN(n) ? null : n;
  },
  date: (x: unknown) => {
    const d = x instanceof Date ? x : new Date(String(x));
    return isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10);
  },
  "date and time": (x: unknown) => {
    const d = x instanceof Date ? x : new Date(String(x));
    return isNaN(d.getTime()) ? null : d.toISOString();
  },
  now: () => new Date().toISOString(),
  today: () => calendarToday(),
  duration: (x: unknown) => toDuration(x),
};

// Register a snake_case alias for every space-named builtin.
//
// FEEL spells these with a space (`starts with`), but the editor, the planner
// and the Python evaluator all accept the underscore form too — Python
// registers BOTH spellings explicitly. TypeScript registered only the spaced
// name, so an expression written `starts_with(name, "A")` evaluated correctly
// in the Python runtime and threw "Unknown function" in the SHIPPED one. The
// editor accepted it, the conformance fixtures encoded it, and the generated
// app failed at runtime.
//
// Derived rather than hand-listed on purpose: adding a new space-named
// function now gets its underscore alias automatically, so the two runtimes
// cannot drift apart again by someone remembering one spelling and not the
// other. The reverse direction is covered by the shared conformance suite.
for (const [name, fn] of Object.entries(BUILT_IN_FUNCTIONS)) {
  if (name.includes(" ")) {
    const alias = name.replace(/ /g, "_");
    if (!(alias in BUILT_IN_FUNCTIONS)) {
      BUILT_IN_FUNCTIONS[alias] = fn;
    }
  }
}

function flattenNumbers(args: unknown[]): number[] {
  const result: number[] = [];
  for (const arg of args) {
    if (Array.isArray(arg)) {
      result.push(...flattenNumbers(arg));
    } else {
      const n = Number(arg);
      if (!isNaN(n)) result.push(n);
    }
  }
  return result;
}

// DATES AND MOMENTS ARE TEXT HERE (`date()` gives "2026-10-12", `now()` an ISO
// moment) and a duration is milliseconds, so `+` saw text and a number and
// joined them: date("2026-10-12") + duration("P1D") was "2026-10-1286400000".
// AquaTrack's Edit Log Entry could not find the end of a day in four tries
// (m1dck85j, 2026-10-12). A date or moment and a number of milliseconds now
// add and subtract as time; two of them subtract to the milliseconds between.
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const ISO_MOMENT = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/;

/** A calendar date or a moment as milliseconds, and whether it was a date. */
function asMoment(v: unknown): { ms: number; day: boolean } | null {
  if (v instanceof Date) return isNaN(v.getTime()) ? null : { ms: v.getTime(), day: false };
  if (typeof v !== "string") return null;
  const s = v.trim();
  if (ISO_DAY.test(s)) {
    const ms = Date.parse(s + "T00:00:00Z");
    return isNaN(ms) ? null : { ms, day: true };
  }
  if (ISO_MOMENT.test(s)) {
    const ms = Date.parse(s);
    return isNaN(ms) ? null : { ms, day: false };
  }
  return null;
}

/** Back to the form it came in: a date stays a date, a moment a moment. */
function fromMoment(ms: number, day: boolean): string {
  const iso = new Date(ms).toISOString();
  return day ? iso.slice(0, 10) : iso;
}

const isDuration = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

// A MONTH IS A PLACE ON THE CALENDAR, NOT A NUMBER OF MILLISECONDS. `duration()`
// read only days and clock time, so `duration("P1M")` was nothing and
// `$today + duration("P1M")` was today: a DITANS subscription's first period
// ended the day it began (FLOW-071, 2026-11-18). A duration of days and clock
// time is still milliseconds; one with years or months is a CalendarDuration,
// and a date plus one lands on the same day that many months on, or on the
// last day of a shorter month (31 Jan + P1M = 28 or 29 Feb). Months move
// first, then days and time. A duration that is not one is an error, not 0.
export class CalendarDuration {
  readonly months: number;
  readonly ms: number;
  constructor(months: number, ms: number) {
    this.months = months;
    this.ms = ms;
  }
  negate(): CalendarDuration { return new CalendarDuration(-this.months, -this.ms); }
  /** As ISO 8601 — what it reads as in text, in a message or a column. */
  toString(): string { return isoDuration(this.months, this.ms); }
  toJSON(): string { return this.toString(); }
}

const ISO_DURATION =
  /^(-)?P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$/i;

/** The duration an ISO 8601 string names — milliseconds when it has no years
 *  or months, a CalendarDuration when it has — or null when it names none. */
export function parseDuration(text: string): number | CalendarDuration | null {
  const s = text.trim();
  const m = s.match(ISO_DURATION);
  // "P", "PT" and "P1DT" name no amount: each part present must carry one.
  if (!m || /^-?PT?$/i.test(s) || /T$/i.test(s)) return null;
  const n = (i: number) => (m[i] ? Number(m[i]) : 0);
  const sign = m[1] ? -1 : 1;
  const months = n(2) * 12 + n(3);
  const ms = Math.round(((n(4) * 7 + n(5)) * 86400 + n(6) * 3600 + n(7) * 60 + n(8)) * 1000);
  if (months === 0) return sign * ms;
  return new CalendarDuration(sign * months, sign * ms);
}

/** `duration(x)`: nothing stays nothing; anything else must be a duration. */
function toDuration(x: unknown): number | CalendarDuration | null {
  if (x == null || x === "") return null;
  if (x instanceof CalendarDuration || isDuration(x)) return x;
  const d = parseDuration(String(x));
  if (d === null) {
    throw new Error(`Not a duration: "${String(x)}" — write ISO 8601, e.g. "P1M", "P1Y2M10D", "P30D", "PT2H"`);
  }
  return d;
}

function isoDuration(months: number, ms: number): string {
  if (months !== 0 && ms !== 0 && Math.sign(months) !== Math.sign(ms)) {
    // Mixed signs have no single ISO form; say each part.
    return `${isoDuration(months, 0)} ${isoDuration(0, ms)}`;
  }
  const neg = months < 0 || ms < 0;
  let mo = Math.abs(months);
  let rest = Math.abs(ms) / 1000;
  const y = Math.floor(mo / 12); mo %= 12;
  const d = Math.floor(rest / 86400); rest -= d * 86400;
  const h = Math.floor(rest / 3600); rest -= h * 3600;
  const mi = Math.floor(rest / 60); rest -= mi * 60;
  const date = (y ? `${y}Y` : "") + (mo ? `${mo}M` : "") + (d ? `${d}D` : "");
  const time = (h ? `${h}H` : "") + (mi ? `${mi}M` : "") + (rest ? `${+rest.toFixed(3)}S` : "");
  const body = date + (time ? `T${time}` : "");
  return (neg ? "-" : "") + "P" + (body || "T0S");
}

/** A moment moved by a calendar duration: months first (the day kept, or the
 *  month's last day when it has fewer), then days and clock time. In UTC. */
function shiftByCalendar(ms: number, d: CalendarDuration): number {
  const t = new Date(ms);
  const monthIndex = t.getUTCMonth() + d.months;
  const year = t.getUTCFullYear() + Math.floor(monthIndex / 12);
  const month = ((monthIndex % 12) + 12) % 12;
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const moved = Date.UTC(year, month, Math.min(t.getUTCDate(), lastDay),
    t.getUTCHours(), t.getUTCMinutes(), t.getUTCSeconds(), t.getUTCMilliseconds());
  return moved + d.ms;
}

const asCalendar = (v: unknown): CalendarDuration | null =>
  v instanceof CalendarDuration ? v : isDuration(v) ? new CalendarDuration(0, v) : null;

// A DATE'S PARTS, AS FEEL NAMES THEM. Data Collector 4 built its reference
// numbers from date($today).year, .month and .day; each read as nothing and
// every new reference came out "REF--0002" (60v142ju, 2026-10-12). In UTC,
// like every moment here; weekday is 1 (Monday) to 7 (Sunday).
const DATE_PARTS = new Set(["year", "month", "day", "weekday", "hour", "minute", "second"]);

/** The part of a date or moment, or undefined when `v` is not one or `part`
 *  is not a date part (the caller then reads it as an ordinary field). */
function datePart(v: unknown, part: string): number | undefined {
  if (!DATE_PARTS.has(part)) return undefined;
  const m = asMoment(v);
  if (!m) return undefined;
  const d = new Date(m.ms);
  switch (part) {
    case "year": return d.getUTCFullYear();
    case "month": return d.getUTCMonth() + 1;
    case "day": return d.getUTCDate();
    case "weekday": return ((d.getUTCDay() + 6) % 7) + 1;
    case "hour": return d.getUTCHours();
    case "minute": return d.getUTCMinutes();
    default: return d.getUTCSeconds();
  }
}

function toNumber(x: unknown): number {
  const n = Number(x);
  return isNaN(n) ? 0 : n;
}

/** Today as the calendar shows it where the app runs — "2026-10-12" — the
 *  same date a step's `$today` writes. */
function calendarToday(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function resolveIdentifier(name: string, ctx: Context): unknown {
  // THE CLOCK, BY THE NAMES STEPS USE. An expression read `$today` as an
  // unknown variable — nothing — though every step template resolved it, so
  // Data Collector 4's date(\$today).year was empty (60v142ju, 2026-10-12).
  // A variable of that name, if a process has one, still wins.
  if ((name === "$today" || name === "$now") && !(name in ctx)) {
    return name === "$today" ? calendarToday() : new Date().toISOString();
  }
  // THE PERSON RUNNING IT, BY THE NAME STEPS USE. A step's value `$user.id` was
  // the signed-in person, but an expression read `$user` as an unknown
  // variable: every guard `candidate.id = $user.id` was false, and 39 of
  // DITANS's processes refused the very owner they protect (wzml1sa6,
  // 2026-10-31). `$user` is the acting user the run holds; a variable of that
  // name, if a process has one, still wins.
  if ((name === "$user" || name.startsWith("$user.")) && !("$user" in ctx)) {
    let who: unknown = (ctx as Record<string, unknown>).user ?? (ctx as Record<string, unknown>).__user ?? null;
    for (const part of name.split(".").slice(1)) {
      if (who == null || typeof who !== "object") return null;
      who = (who as Record<string, unknown>)[part];
    }
    return who === undefined ? null : who;
  }
  // Handle dotted names: "customer.age"
  const parts = name.split(".");
  let current: unknown = ctx;
  for (const part of parts) {
    // A DATE'S OWN PARTS: `logged.year`, `d.month` (FEEL's date properties).
    const dp = datePart(current, part);
    if (dp !== undefined) { current = dp; continue; }
    // An ABSENT field is null, not undefined — matching the Python engine so a
    // condition evaluates identically in the editor playground and here in the
    // shipped app. Pinned by the FEEL cross-engine conformance suite.
    if (current == null || typeof current !== "object") return null;
    // A path on a list is the list of each item's value (FEEL): `items.subtotal`.
    if (Array.isArray(current) && !(part in current)) {
      current = current.map((el) => (el != null && typeof el === "object" ? (el as Record<string, unknown>)[part] : null));
      continue;
    }
    current = (current as Record<string, unknown>)[part];
  }
  return current === undefined ? null : current;
}

// Equality mirroring the Python engine's `_fuzzy_equal`: numeric coercion when
// both sides parse as numbers, else case-insensitive string compare, with null
// handling. Keeps this shipped runtime in lockstep with the editor playground.
function fuzzyEqual(a: unknown, b: unknown): boolean {
  if (a === null && b === null) return true;
  if (a === null || b === null) return false;
  const emptyish = (v: unknown) => typeof v === "string" && v.trim() === "";
  if (!emptyish(a) && !emptyish(b)) {
    const na = Number(a);
    const nb = Number(b);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na === nb;
  }
  return String(a).toLowerCase() === String(b).toLowerCase();
}

export function evaluate(node: ASTNode, ctx: Context): unknown {
  switch (node.type) {
    case "NumberLiteral":
      return node.value;
    case "StringLiteral":
      return node.value;
    case "BooleanLiteral":
      return node.value;
    case "NullLiteral":
      return null;
    case "WildcardExpression":
      return Symbol.for("FEEL_WILDCARD");

    case "Identifier":
      return resolveIdentifier(node.name, ctx);

    case "MemberExpression": {
      const obj = evaluate(node.object, ctx);
      const dp = datePart(obj, node.property);
      if (dp !== undefined) return dp;
      if (obj == null || typeof obj !== "object") return undefined;
      // A PATH ON A LIST IS THE LIST OF EACH ITEM'S VALUE (FEEL's own rule).
      // `sum(items.subtotal)` read `subtotal` off the array, got nothing, and
      // F&B's every order totalled 0 (2026-10-01). A list's own properties
      // (`length`) still answer as before.
      if (Array.isArray(obj) && !(node.property in obj)) {
        return obj.map((el) => (el != null && typeof el === "object" ? (el as Record<string, unknown>)[node.property] : undefined));
      }
      return (obj as Record<string, unknown>)[node.property];
    }

    case "UnaryExpression": {
      const raw = evaluate(node.operand, ctx);
      if (raw instanceof CalendarDuration) return node.operator === "-" ? raw.negate() : raw;
      const val = toNumber(raw);
      return node.operator === "-" ? -val : val;
    }

    case "BinaryExpression": {
      const left = evaluate(node.left, ctx);
      const right = evaluate(node.right, ctx);
      const l = toNumber(left);
      const r = toNumber(right);

      const lm = asMoment(left);
      const rm = asMoment(right);
      if (node.operator === "+") {
        if (lm && isDuration(right)) return fromMoment(lm.ms + right, lm.day);
        if (rm && isDuration(left)) return fromMoment(rm.ms + left, rm.day);
        if (lm && right instanceof CalendarDuration) return fromMoment(shiftByCalendar(lm.ms, right), lm.day);
        if (rm && left instanceof CalendarDuration) return fromMoment(shiftByCalendar(rm.ms, left), rm.day);
      }
      if (node.operator === "-") {
        if (lm && rm) return lm.ms - rm.ms;
        if (lm && isDuration(right)) return fromMoment(lm.ms - right, lm.day);
        if (lm && right instanceof CalendarDuration) return fromMoment(shiftByCalendar(lm.ms, right.negate()), lm.day);
      }
      // Durations with months add, subtract and scale as durations.
      if (left instanceof CalendarDuration || right instanceof CalendarDuration) {
        const lc = asCalendar(left);
        const rc = asCalendar(right);
        if (lc && rc && node.operator === "+") return new CalendarDuration(lc.months + rc.months, lc.ms + rc.ms);
        if (lc && rc && node.operator === "-") return new CalendarDuration(lc.months - rc.months, lc.ms - rc.ms);
        if (node.operator === "*") {
          const c = (left instanceof CalendarDuration ? left : right) as CalendarDuration;
          const k = Number(left instanceof CalendarDuration ? right : left);
          if (Number.isInteger(k)) return new CalendarDuration(c.months * k, c.ms * k);
          throw new Error(`A duration of months is multiplied by a whole number, not ${String(left instanceof CalendarDuration ? right : left)}`);
        }
      }

      switch (node.operator) {
        case "+":
          // String concatenation if either is a string and non-numeric
          if (typeof left === "string" || typeof right === "string") {
            return String(left ?? "") + String(right ?? "");
          }
          return l + r;
        case "-":
          return l - r;
        case "*":
          return l * r;
        case "/":
          return r === 0 ? null : l / r;
        case "%":
          return r === 0 ? null : l % r;
        case "^":
          return Math.pow(l, r);
      }
      break;
    }

    case "ComparisonExpression": {
      const left = evaluate(node.left, ctx);
      const right = evaluate(node.right, ctx);

      // Equality/inequality use fuzzy-equal (numeric coercion + case-insensitive
      // + null handling), matching the Python engine and the editor playground.
      if (node.operator === "=") return fuzzyEqual(left, right);
      if (node.operator === "!=") return !fuzzyEqual(left, right);

      // Ordering (<, <=, >, >=): a null operand yields false.
      if (left === null || right === null) {
        return false;
      }

      // Numeric comparison — coerce numeric STRINGS too (a numeric/bigint column
      // comes back from node-postgres as a string, and trigger fields are spread
      // in uncoerced), so `age >= 18` with age="9" compares 9 >= 18, not the
      // lexicographic "9" >= "18" (which is true and wrong). Matches fuzzyEqual
      // (used by = / !=) and the Python engine. Empty string is NOT a number.
      const asNum = (v: unknown): number =>
        typeof v === "number" ? v
        : (typeof v === "string" && v.trim() !== "") ? Number(v)
        : NaN;
      const ln = asNum(left);
      const rn = asNum(right);
      if (Number.isFinite(ln) && Number.isFinite(rn)) {
        switch (node.operator) {
          case "<": return ln < rn;
          case "<=": return ln <= rn;
          case ">": return ln > rn;
          case ">=": return ln >= rn;
        }
      }

      // String comparison (non-numeric operands, e.g. ISO dates)
      const ls = String(left);
      const rs = String(right);
      switch (node.operator) {
        case "<": return ls < rs;
        case "<=": return ls <= rs;
        case ">": return ls > rs;
        case ">=": return ls >= rs;
      }
      break;
    }

    case "LogicalExpression": {
      const left = evaluate(node.left, ctx);
      if (node.operator === "??") {
        // Empty is null, undefined or "": a field never filled reads as "".
        return left === null || left === undefined || left === "" ? evaluate(node.right, ctx) : left;
      }
      if (node.operator === "or") {
        return Boolean(left) || Boolean(evaluate(node.right, ctx));
      }
      return Boolean(left) && Boolean(evaluate(node.right, ctx));
    }

    case "NotExpression":
      return !Boolean(evaluate(node.operand, ctx));

    case "IfExpression": {
      const cond = evaluate(node.condition, ctx);
      return Boolean(cond)
        ? evaluate(node.thenBranch, ctx)
        : evaluate(node.elseBranch, ctx);
    }

    case "InExpression": {
      const value = evaluate(node.value, ctx);
      return matchValue(value, node.list, ctx);
    }

    case "BetweenExpression": {
      const val = toNumber(evaluate(node.value, ctx));
      const low = toNumber(evaluate(node.low, ctx));
      const high = toNumber(evaluate(node.high, ctx));
      return val >= low && val <= high;
    }

    case "RangeExpression": {
      // When evaluated standalone (not in InExpression), return a range descriptor
      return {
        __range: true,
        startInclusive: node.startInclusive,
        endInclusive: node.endInclusive,
        start: evaluate(node.start, ctx),
        end: evaluate(node.end, ctx),
      };
    }

    case "ListExpression":
      return node.elements.map((el) => evaluate(el, ctx));

    case "FunctionCall": {
      const fn = BUILT_IN_FUNCTIONS[node.name];
      if (!fn) {
        throw new Error(`Unknown function: ${node.name}`);
      }
      const args = node.args.map((a) => evaluate(a, ctx));
      return fn(...args);
    }
  }

  return null;
}

/** Check if a value matches a FEEL-lite pattern (range, list, or single value). */
export function matchValue(
  value: unknown,
  pattern: ASTNode,
  ctx: Context,
): boolean {
  if (pattern.type === "WildcardExpression") {
    return true;
  }

  if (pattern.type === "RangeExpression") {
    const v = toNumber(value);
    const start = toNumber(evaluate(pattern.start, ctx));
    const end = toNumber(evaluate(pattern.end, ctx));
    const startOk = pattern.startInclusive ? v >= start : v > start;
    const endOk = pattern.endInclusive ? v <= end : v < end;
    return startOk && endOk;
  }

  if (pattern.type === "ListExpression") {
    return pattern.elements.some((el) => {
      if (el.type === "RangeExpression") {
        return matchValue(value, el, ctx);
      }
      const elVal = evaluate(el, ctx);
      return value === elVal || String(value) === String(elVal);
    });
  }

  if (pattern.type === "NotExpression") {
    return !matchValue(value, pattern.operand, ctx);
  }

  // Single value comparison
  const patternVal = evaluate(pattern, ctx);
  return value === patternVal || String(value) === String(patternVal);
}

/** Evaluate a FEEL-lite expression string against a context. */
export function evaluateExpression(
  expr: string,
  ctx: Context,
): unknown {
  if (!expr || !expr.trim()) return null;

  // Import lazily to avoid circular dependency
  const { tokenize } = require("./tokenizer");
  const { parse } = require("./parser");

  const tokens = tokenize(expr);
  const ast = parse(tokens);
  return evaluate(ast, ctx);
}
