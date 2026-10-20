/**
 * Decision tables — the one implementation.
 *
 * Used by the rules engine (a table on a record, on every save), by the
 * workflow `decision` step (a table over a workflow's data) and, bundled, by
 * the platform's editor (checking cells at save, and the "Test it" panel). It
 * was three: the engine's matcher (no ranges), the workflow's (no FEEL, hit
 * policy read as words the Blueprint never writes) and the editor's — so a row
 * could match in the editor and not in the app.
 *
 * A TABLE is inputs (fields read), outputs (fields written) and rows; a row
 * matches when every input cell matches. A HIT POLICY says which matches win:
 *
 *   U  Unique      at most one row may match; two matching is the author's
 *                  mistake — refused at save (see analyzeTable), and at run
 *                  time the first is used and the violation reported.
 *   F  First       the first matching row, top to bottom.
 *   P  Priority    the matching row whose output value comes first in that
 *                  output's list of values (e.g. reject before review before
 *                  approve); without a list, the first match.
 *   A  Any         every matching row must give the same outputs.
 *   C  Collect     every match: with an aggregation (SUM, COUNT, MIN, MAX) one
 *                  value per output; without, a list per output.
 *   R  Rule order  every match, as a list in row order.
 *
 * A CELL (input) is one of — combine alternatives with a comma:
 *
 *   -   or empty         anything
 *   travel  "travel"     equal to the text (bare words are text)
 *   5000  true  null     equal to the number / yes-no / nothing
 *   > 5000   <= 10       compared (to a number, a date "2026-01-01", or a field)
 *   != travel            anything but
 *   [1..10]  (0..5]      a range; [ ] include the end, ( ) exclude it
 *   not(travel, meals)   none of these
 *
 * Pure: no I/O, no imports beyond the FEEL evaluator.
 */
import { evaluateExpression } from "../feel-lite";

export type HitPolicy = "U" | "F" | "P" | "A" | "C" | "R";
export type Aggregation = "SUM" | "COUNT" | "MIN" | "MAX";
type Scalar = string | number | boolean | null;

export interface TableColumn {
  id?: string;
  name: string;
  label?: string;
  type?: string;
  variableBinding?: string;
  /** The values this column takes, in priority order (for P, and to catch typos). */
  values?: string[];
}

export interface TableRow {
  id?: string;
  inputEntries?: string[];
  outputEntries?: string[];
  annotation?: string;
}

export interface DecisionTableDef {
  hitPolicy?: string;
  aggregation?: string;
  inputs?: TableColumn[];
  outputs?: TableColumn[];
  rules?: TableRow[];
}

export type Constraint =
  | { kind: "any" }
  | { kind: "set"; values: Scalar[] }
  | { kind: "interval"; lo?: number; loInc: boolean; hi?: number; hiInc: boolean; dates: boolean }
  | { kind: "not"; inner: Constraint }
  | { kind: "union"; parts: Constraint[] }
  | { kind: "expr"; op: string; field: string };

export interface CellParse {
  ok: boolean;
  constraint?: Constraint;
  error?: string;
}

const WORDS: Record<string, HitPolicy> = {
  u: "U", unique: "U", f: "F", first: "F", p: "P", priority: "P", a: "A", any: "A",
  c: "C", collect: "C", r: "R", "rule order": "R", rule_order: "R", ruleorder: "R",
  "output order": "R", o: "R",
};

/** The policy, from a letter or a word; unknown means First. */
export function normalizeHitPolicy(raw: unknown): HitPolicy {
  return WORDS[String(raw ?? "F").trim().toLowerCase()] ?? "F";
}

export function normalizeAggregation(raw: unknown): Aggregation | undefined {
  const a = String(raw ?? "").trim().toUpperCase();
  return a === "SUM" || a === "COUNT" || a === "MIN" || a === "MAX" ? a : undefined;
}

// --------------------------------------------------------------------------- //
// Reading a cell
// --------------------------------------------------------------------------- //

/** Split on a separator outside quotes, brackets and parentheses. */
export function splitTopLevel(s: string, sep = ","): string[] {
  const out: string[] = [];
  let depth = 0, quote: string | null = null, cur = "";
  for (const ch of s) {
    if (quote) {
      cur += ch;
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
    if (ch === "(" || ch === "[") depth++;
    if (ch === ")" || ch === "]") depth = Math.max(0, depth - 1);
    if (ch === sep && depth === 0) { out.push(cur); cur = ""; continue; }
    cur += ch;
  }
  out.push(cur);
  return out;
}

const NUM = /^[+-]?\d+(?:\.\d+)?$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?$/;
const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;

function unquote(s: string): string | null {
  const m = s.match(/^"(.*)"$|^'(.*)'$/s);
  return m ? (m[1] ?? m[2] ?? "") : null;
}

/** A literal: quoted text, number, yes/no, null, a date("…"), or a bare word (text). */
function literal(raw: string): { ok: boolean; value?: Scalar; error?: string } {
  const s = raw.trim();
  if (!s) return { ok: false, error: "a value is missing" };
  const q = unquote(s);
  if (q !== null) return { ok: true, value: q };
  if ((s.startsWith('"') || s.startsWith("'")) && !q) return { ok: false, error: `the quote in ${s} is not closed` };
  if (NUM.test(s)) return { ok: true, value: Number(s) };
  if (s === "true" || s === "false") return { ok: true, value: s === "true" };
  if (s === "null") return { ok: true, value: null };
  const d = s.match(/^date\(\s*["'](.+)["']\s*\)$/);
  if (d) return ISO_DATE.test(d[1]) ? { ok: true, value: d[1] } : { ok: false, error: `${d[1]} is not a date` };
  if (/[<>=!()[\]]/.test(s)) return { ok: false, error: `“${s}” cannot be read as a value` };
  return { ok: true, value: s }; // a bare word is text: travel, approved
}

/** A range endpoint: a number or a date. */
function endpoint(raw: string): { ok: boolean; n?: number; date?: boolean; error?: string } {
  const lit = literal(raw);
  if (!lit.ok) return { ok: false, error: lit.error };
  if (typeof lit.value === "number") return { ok: true, n: lit.value, date: false };
  if (typeof lit.value === "string" && ISO_DATE.test(lit.value)) {
    const t = Date.parse(lit.value);
    if (!Number.isNaN(t)) return { ok: true, n: t, date: true };
  }
  return { ok: false, error: `a range needs numbers or dates, not “${raw.trim()}”` };
}

function parsePart(part: string): CellParse {
  const s = part.trim();
  if (s === "" || s === "-" || s === "*" || s.toLowerCase() === "any") return { ok: true, constraint: { kind: "any" } };
  const neg = s.match(/^not\s*\((.*)\)$/is);
  if (neg) {
    const inner = parseCell(neg[1]);
    return inner.ok ? { ok: true, constraint: { kind: "not", inner: inner.constraint! } } : inner;
  }
  const range = s.match(/^([[(\]])\s*(.+?)\s*\.\.\s*(.+?)\s*([\])[])$/);
  if (range) {
    const lo = endpoint(range[2]);
    const hi = endpoint(range[3]);
    if (!lo.ok) return { ok: false, error: lo.error };
    if (!hi.ok) return { ok: false, error: hi.error };
    if (lo.date !== hi.date) return { ok: false, error: "both ends of a range must be numbers, or both dates" };
    if (lo.n! > hi.n!) return { ok: false, error: `the range starts after it ends (${range[2].trim()} > ${range[3].trim()})` };
    return { ok: true, constraint: { kind: "interval", lo: lo.n, loInc: range[1] === "[", hi: hi.n, hiInc: range[4] === "]", dates: !!lo.date } };
  }
  if (/^(>=|<=|!=|<>|>|<|=)$/.test(s)) return { ok: false, error: `“${s}” needs a value after it` };
  const cmp = s.match(/^(>=|<=|!=|<>|>|<|=)\s*(.+)$/);
  if (cmp) {
    const op = cmp[1] === "<>" ? "!=" : cmp[1];
    const rhs = cmp[2].trim();
    if (op === "=" || op === "!=") {
      const lit = literal(rhs);
      if (!lit.ok) return { ok: false, error: lit.error };
      const set: Constraint = { kind: "set", values: [lit.value!] };
      return { ok: true, constraint: op === "=" ? set : { kind: "not", inner: set } };
    }
    const ep = endpoint(rhs);
    if (!ep.ok) {
      // Compared to another field of the record: `> budget`.
      if (IDENT.test(rhs) && !["true", "false", "null"].includes(rhs)) {
        return { ok: true, constraint: { kind: "expr", op, field: rhs } };
      }
      return { ok: false, error: `${op} needs a number, a date or a field, not “${rhs}”` };
    }
    const iv: Constraint =
      op === ">" ? { kind: "interval", lo: ep.n, loInc: false, hiInc: false, dates: !!ep.date }
      : op === ">=" ? { kind: "interval", lo: ep.n, loInc: true, hiInc: false, dates: !!ep.date }
      : op === "<" ? { kind: "interval", hi: ep.n, hiInc: false, loInc: false, dates: !!ep.date }
      : { kind: "interval", hi: ep.n, hiInc: true, loInc: false, dates: !!ep.date };
    return { ok: true, constraint: iv };
  }
  const lit = literal(s);
  return lit.ok ? { ok: true, constraint: { kind: "set", values: [lit.value!] } } : { ok: false, error: lit.error };
}

/** Read one input cell. */
export function parseCell(cell: unknown): CellParse {
  const s = String(cell ?? "").trim();
  const parts = splitTopLevel(s).map((p) => p.trim());
  if (parts.length <= 1) return parsePart(s);
  if (parts.some((p) => p === "")) return { ok: false, error: "an alternative between commas is empty" };
  const parsed = parts.map(parsePart);
  const bad = parsed.find((p) => !p.ok);
  if (bad) return bad;
  // Plain values merge into one set: travel, meals, office.
  const sets = parsed.filter((p) => p.constraint!.kind === "set").flatMap((p) => (p.constraint as any).values);
  const rest = parsed.filter((p) => p.constraint!.kind !== "set").map((p) => p.constraint!);
  if (rest.some((c) => c.kind === "any")) return { ok: true, constraint: { kind: "any" } };
  const parts2: Constraint[] = [...(sets.length ? [{ kind: "set", values: sets } as Constraint] : []), ...rest];
  return { ok: true, constraint: parts2.length === 1 ? parts2[0] : { kind: "union", parts: parts2 } };
}

// --------------------------------------------------------------------------- //
// Matching
// --------------------------------------------------------------------------- //

function asNumber(v: unknown, dates: boolean): number | null {
  if (v === null || v === undefined || v === "") return null;
  if (dates) {
    if (v instanceof Date) return v.getTime();
    const t = Date.parse(String(v));
    return Number.isNaN(t) ? null : t;
  }
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && NUM.test(v.trim())) return Number(v.trim());
  return null;
}

function sameValue(v: unknown, want: Scalar): boolean {
  if (want === null) return v === null || v === undefined || v === "";
  if (typeof want === "number") {
    const n = asNumber(v, false);
    return n !== null && n === want;
  }
  if (typeof want === "boolean") return v === want || String(v) === String(want);
  return String(v ?? "").trim() === want;
}

export function matchConstraint(c: Constraint, value: unknown, ctx: Record<string, unknown> = {}): boolean {
  switch (c.kind) {
    case "any": return true;
    case "set": return c.values.some((w) => sameValue(value, w));
    case "interval": {
      const n = asNumber(value, c.dates);
      if (n === null) return false;
      if (c.lo !== undefined && (c.loInc ? n < c.lo : n <= c.lo)) return false;
      if (c.hi !== undefined && (c.hiInc ? n > c.hi : n >= c.hi)) return false;
      return true;
    }
    case "not": return !matchConstraint(c.inner, value, ctx);
    case "union": return c.parts.some((p) => matchConstraint(p, value, ctx));
    case "expr": {
      const other = ctx[c.field];
      const a = asNumber(value, false), b = asNumber(other, false);
      const da = a ?? asNumber(value, true), db = b ?? asNumber(other, true);
      if (da === null || db === null) return false;
      return c.op === ">" ? da > db : c.op === ">=" ? da >= db : c.op === "<" ? da < db : da <= db;
    }
  }
}

/** An output cell's value: text, number, yes/no, null — or a FEEL expression over the data. */
export function outputValue(cell: unknown, ctx: Record<string, unknown> = {}): unknown {
  const c = String(cell ?? "").trim();
  if (c === "" || c === "-") return undefined;
  const q = unquote(c);
  if (q !== null) return q;
  if (NUM.test(c)) return Number(c);
  if (c === "true") return true;
  if (c === "false") return false;
  if (c === "null") return null;
  if (IDENT.test(c) && !(c in ctx)) return c; // a bare word is text: approved
  try {
    const v = evaluateExpression(c, ctx as any);
    return v === undefined ? c : v;
  } catch {
    return c;
  }
}

function bindingOf(col: TableColumn): string {
  return String(col.variableBinding || col.name || "");
}

export interface TableResult {
  policy: HitPolicy;
  /** Row indexes (0-based) whose every input cell matched. */
  matched: number[];
  /** The rows whose outputs were used. */
  used: number[];
  /** Output field -> value (a list under C without aggregation, and under R). */
  outputs: Record<string, unknown>;
  /** Said when the hit policy was broken: two rows under Unique, disagreeing rows under Any. */
  violation?: string;
}

/** Evaluate a table over a record (or a workflow's variables). */
export function evaluateTable(table: DecisionTableDef, ctx: Record<string, unknown>): TableResult {
  const policy = normalizeHitPolicy(table.hitPolicy);
  const inputs = table.inputs || [];
  const outputs = table.outputs || [];
  const rows = table.rules || [];
  const parsedInputs = rows.map((r) => inputs.map((_, i) => parseCell((r.inputEntries || [])[i])));
  const matched: number[] = [];
  rows.forEach((row, ri) => {
    const ok = inputs.every((col, ci) => {
      const p = parsedInputs[ri][ci];
      if (!p.ok) return false; // a cell the engine cannot read matches nothing
      return matchConstraint(p.constraint!, ctx[bindingOf(col)], ctx);
    });
    if (ok) matched.push(ri);
  });
  const valuesOf = (ri: number) => {
    const o: Record<string, unknown> = {};
    outputs.forEach((col, ci) => {
      const v = outputValue((rows[ri].outputEntries || [])[ci], ctx);
      if (v !== undefined) o[bindingOf(col)] = v;
    });
    return o;
  };
  const result: TableResult = { policy, matched, used: [], outputs: {} };
  if (!matched.length) return result;

  if (policy === "C" || policy === "R") {
    const agg = policy === "C" ? normalizeAggregation(table.aggregation) : undefined;
    result.used = [...matched];
    for (const col of outputs) {
      const field = bindingOf(col);
      const vals = matched.map((ri) => valuesOf(ri)[field]).filter((v) => v !== undefined);
      if (!agg) { result.outputs[field] = vals; continue; }
      if (agg === "COUNT") { result.outputs[field] = vals.length; continue; }
      const nums = vals.map((v) => asNumber(v, false)).filter((n): n is number => n !== null);
      result.outputs[field] = !nums.length ? null
        : agg === "SUM" ? nums.reduce((a, b) => a + b, 0)
        : agg === "MIN" ? Math.min(...nums) : Math.max(...nums);
    }
    return result;
  }

  let winner = matched[0];
  if (policy === "U" && matched.length > 1) {
    result.violation = `More than one row matched a Unique table (rows ${matched.map((i) => i + 1).join(", ")}); the first was used.`;
  }
  if (policy === "A" && matched.length > 1) {
    const first = JSON.stringify(valuesOf(matched[0]));
    if (matched.some((ri) => JSON.stringify(valuesOf(ri)) !== first)) {
      result.violation = `Rows ${matched.map((i) => i + 1).join(", ")} matched an Any table but disagree; the first was used.`;
    }
  }
  if (policy === "P" && matched.length > 1) {
    const ranked = outputs.find((col) => Array.isArray(col.values) && col.values.length);
    if (ranked) {
      const order = (ranked.values || []).map(String);
      const rank = (ri: number) => {
        const v = valuesOf(ri)[bindingOf(ranked)];
        const i = order.indexOf(String(v));
        return i < 0 ? order.length : i;
      };
      winner = [...matched].sort((a, b) => rank(a) - rank(b) || a - b)[0];
    }
  }
  result.used = [winner];
  result.outputs = valuesOf(winner);
  return result;
}

// --------------------------------------------------------------------------- //
// Analysis — what can be proven wrong with a table before anyone uses it
// --------------------------------------------------------------------------- //

type Tri = true | false | "maybe";

function setVsInterval(values: Scalar[], c: Extract<Constraint, { kind: "interval" }>): Tri {
  return values.some((v) => matchConstraint(c, v)) ? true : false;
}

/** Can one value satisfy both? Only definite answers are acted on. */
export function intersects(a: Constraint, b: Constraint): Tri {
  if (a.kind === "any" || b.kind === "any") return true;
  if (a.kind === "expr" || b.kind === "expr") return "maybe";
  if (a.kind === "union") return orTri(a.parts.map((p) => intersects(p, b)));
  if (b.kind === "union") return orTri(b.parts.map((p) => intersects(a, p)));
  if (a.kind === "set" && b.kind === "set") return a.values.some((x) => b.values.some((y) => sameValue(x, y)));
  if (a.kind === "set" && b.kind === "interval") return setVsInterval(a.values, b);
  if (a.kind === "interval" && b.kind === "set") return setVsInterval(b.values, a);
  if (a.kind === "interval" && b.kind === "interval") {
    if (a.dates !== b.dates) return false;
    const lo = Math.max(a.lo ?? -Infinity, b.lo ?? -Infinity);
    const hi = Math.min(a.hi ?? Infinity, b.hi ?? Infinity);
    if (lo < hi) return true;
    if (lo > hi) return false;
    const loInc = (a.lo === lo ? a.loInc : true) && (b.lo === lo ? b.loInc : true);
    const hiInc = (a.hi === hi ? a.hiInc : true) && (b.hi === hi ? b.hiInc : true);
    return loInc && hiInc;
  }
  if (a.kind === "not" && b.kind === "set") return b.values.some((v) => !matchConstraint(a, v));
  if (b.kind === "not" && a.kind === "set") return a.values.some((v) => !matchConstraint(b, v));
  return "maybe";
}

function orTri(xs: Tri[]): Tri {
  if (xs.includes(true)) return true;
  return xs.includes("maybe") ? "maybe" : false;
}

/** Does `a` accept everything `b` accepts? Only a definite yes is acted on. */
export function covers(a: Constraint, b: Constraint): Tri {
  if (a.kind === "any") return true;
  if (b.kind === "any") return false;
  if (a.kind === "expr" || b.kind === "expr") return "maybe";
  if (b.kind === "union") {
    const each = b.parts.map((p) => covers(a, p));
    return each.every((x) => x === true) ? true : each.includes(false) ? false : "maybe";
  }
  if (b.kind === "set") return b.values.every((v) => matchConstraint(a, v)) ? true : false;
  if (a.kind === "interval" && b.kind === "interval") {
    if (a.dates !== b.dates) return false;
    const loOk = a.lo === undefined || (b.lo !== undefined && (b.lo > a.lo || (b.lo === a.lo && (a.loInc || !b.loInc))));
    const hiOk = a.hi === undefined || (b.hi !== undefined && (b.hi < a.hi || (b.hi === a.hi && (a.hiInc || !b.hiInc))));
    return loOk && hiOk;
  }
  if (a.kind === "union") return a.parts.some((p) => covers(p, b) === true) ? true : "maybe";
  return "maybe";
}

export interface TableFinding {
  /** error: refused at save. warning: said, saved. */
  severity: "error" | "warning";
  kind: "cell" | "overlap" | "unreachable" | "shape" | "value";
  row?: number;
  column?: string;
  message: string;
}

/** Everything that can be proven about a table without any data. Rows are 1-based in messages. */
export function analyzeTable(table: DecisionTableDef): TableFinding[] {
  const out: TableFinding[] = [];
  const policy = normalizeHitPolicy(table.hitPolicy);
  const inputs = table.inputs || [];
  const outputs = table.outputs || [];
  const rows = table.rules || [];
  if (!inputs.length) out.push({ severity: "error", kind: "shape", message: "Add at least one input column — a field the table reads." });
  if (!outputs.length) out.push({ severity: "error", kind: "shape", message: "Add at least one output column — a field the table sets." });
  if (!rows.length) out.push({ severity: "error", kind: "shape", message: "Add at least one row." });
  if (policy === "C" && table.aggregation && !normalizeAggregation(table.aggregation)) {
    out.push({ severity: "error", kind: "shape", message: `“${table.aggregation}” is not an aggregation — use SUM, COUNT, MIN or MAX.` });
  }

  const parsed: (Constraint | null)[][] = rows.map((row, ri) => inputs.map((col, ci) => {
    const p = parseCell((row.inputEntries || [])[ci]);
    if (!p.ok) {
      out.push({ severity: "error", kind: "cell", row: ri + 1, column: col.label || col.name,
                 message: `Row ${ri + 1}, ${col.label || col.name}: ${p.error}.` });
      return null;
    }
    const allowed = (col.values || []).map(String);
    if (allowed.length && p.constraint) {
      const lits = p.constraint.kind === "set" ? p.constraint.values
        : p.constraint.kind === "not" && p.constraint.inner.kind === "set" ? p.constraint.inner.values : [];
      for (const v of lits) {
        if (v !== null && !allowed.includes(String(v))) {
          out.push({ severity: "error", kind: "value", row: ri + 1, column: col.label || col.name,
                     message: `Row ${ri + 1}, ${col.label || col.name}: “${v}” is not one of ${allowed.join(", ")}.` });
        }
      }
    }
    if ((col.type === "number" || col.type === "date") && p.constraint?.kind === "set") {
      for (const v of p.constraint.values) {
        const wrong = col.type === "number" ? typeof v === "string" : typeof v === "string" && !ISO_DATE.test(v);
        if (wrong) {
          out.push({ severity: "error", kind: "value", row: ri + 1, column: col.label || col.name,
                     message: `Row ${ri + 1}, ${col.label || col.name}: “${v}” is not a ${col.type}.` });
        }
      }
    }
    return p.constraint ?? null;
  }));
  rows.forEach((row, ri) => {
    outputs.forEach((col, ci) => {
      const cell = String((row.outputEntries || [])[ci] ?? "").trim();
      const allowed = (col.values || []).map(String);
      const q = unquote(cell);
      const word = q ?? (cell && !NUM.test(cell) && IDENT.test(cell) ? cell : null);
      if (allowed.length && word !== null && cell !== "" && cell !== "-" && !allowed.includes(word)) {
        out.push({ severity: "error", kind: "value", row: ri + 1, column: col.label || col.name,
                   message: `Row ${ri + 1}, ${col.label || col.name}: “${word}” is not one of ${allowed.join(", ")}.` });
      }
      if ((cell.startsWith('"') || cell.startsWith("'")) && q === null) {
        out.push({ severity: "error", kind: "cell", row: ri + 1, column: col.label || col.name,
                   message: `Row ${ri + 1}, ${col.label || col.name}: the quote is not closed.` });
      }
    });
  });

  const complete = (ri: number) => parsed[ri].every((c) => c !== null);
  if (policy === "U") {
    for (let i = 0; i < rows.length; i++) {
      for (let j = i + 1; j < rows.length; j++) {
        if (!complete(i) || !complete(j)) continue;
        const all = parsed[i].map((c, k) => intersects(c!, parsed[j][k]!));
        if (all.every((x) => x === true)) {
          out.push({ severity: "error", kind: "overlap", row: j + 1,
                     message: `Rows ${i + 1} and ${j + 1} can both match the same record, which a Unique table does not allow. Narrow one of them, or use First.` });
        }
      }
    }
  }
  if (policy === "F" || policy === "U" || policy === "A" || policy === "P") {
    for (let j = 1; j < rows.length; j++) {
      if (!complete(j)) continue;
      for (let i = 0; i < j; i++) {
        if (!complete(i)) continue;
        if (parsed[i].every((c, k) => covers(c!, parsed[j][k]!) === true)) {
          if (policy === "F") {
            out.push({ severity: "warning", kind: "unreachable", row: j + 1,
                       message: `Row ${j + 1} can never be used: row ${i + 1} above it matches everything it does.` });
          }
          break;
        }
      }
    }
  }
  return out;
}
