/**
 * Form Interaction Engine — pure, framework-free foundation (spec item 5, S1).
 *
 * This module owns the *field-interaction contract* (the schema shape a form
 * field's optional `interaction` block takes) and a *pure formula evaluator*
 * for computed fields. It has ZERO React / DOM / fetch dependencies so the
 * reactive form controller (next task), the generator's auto-derivation pass,
 * and the editor authoring panel can all import the same types + evaluator.
 *
 * Non-invention: formulas are evaluated by the EXISTING expression engine
 * (`evalExpression` → feel-lite in `./bindings`). We do NOT introduce a new
 * language and we NEVER use `eval`. feel-lite only calls functions from its own
 * built-in registry (it does not resolve callables from the scope object), so
 * to make the whitelisted interaction-function library available to a formula
 * we pre-resolve those calls to plain values (innermost-first) and hand the
 * residual pure-arithmetic expression to feel-lite. Everything feel-lite
 * already understands (`+ - * /`, comparisons, its own built-ins) is left
 * untouched.
 */

import { evalExpression } from "./bindings";

// ── Contract types ─────────────────────────────────────────────────────────

/** A derived/read-only field: its value comes from a formula over siblings. */
export interface ComputedInteraction {
  /** Expression over sibling field names + INTERACTION_FUNCTIONS. */
  formula: string;
  /** Render the input disabled (default true in practice). */
  readOnly?: boolean;
}

/** A Select whose options are fetched from a resource, optionally filtered. */
export interface DynamicOptions {
  /** Resource slug to fetch options from (e.g. "products"). */
  source: string;
  /** Column used as each option's value (e.g. "id"). */
  value: string;
  /** Column used as each option's label (e.g. "name"). */
  label: string;
  /**
   * Filter map applied to the fetch. Values may contain `{{otherField}}`
   * templates that resolve against the live field-value map, so the options
   * re-fetch when the referenced field changes.
   */
  filter?: Record<string, string>;
}

/** A side-effect: when this field changes, fetch a record and set other fields. */
export interface OnChangeInteraction {
  fetch: {
    /** Resource slug to fetch from. */
    resource: string;
    /** Column on the resource to match against (e.g. "id"). */
    by: string;
    /** This form's field whose value supplies the match (e.g. "customerId"). */
    from: string;
  };
  /**
   * Map of target-field → template. Templates resolve against `{ result }`
   * (the fetched record), e.g. `{ "address": "{{result.address}}" }`.
   */
  set: Record<string, string>;
}

/** The optional `interaction` block on a form field node. */
export interface FieldInteraction {
  computed?: ComputedInteraction;
  optionsFrom?: DynamicOptions;
  /** Field names this field reacts to (drives re-fetch / recompute). */
  dependsOn?: string[];
  onChange?: OnChangeInteraction;
  /**
   * Predicate over sibling field values (feel-lite expression with the
   * same INTERACTION_FUNCTIONS available). When the predicate returns
   * false, the field is hidden from the DOM AND excluded from validation
   * + the submit payload. Example: `"paymentMethod == 'card'"`.
   */
  visibleIf?: string;
  /** When truthy, add a required-marker + fail submit if empty. */
  requiredIf?: string;
  /** When falsy, disable the input (still submitted). */
  enabledIf?: string;
  /** When truthy, make the input read-only (still submitted). */
  readOnlyIf?: string;
}

/**
 * Per-field state derived from the four conditional predicates. Every
 * consumer (form field renderer, submit-payload assembler, validator)
 * reads from this shape so the four predicates compose consistently.
 */
export interface FieldConditionalState {
  visible: boolean;
  required: boolean;
  enabled: boolean;
  readOnly: boolean;
}

const DEFAULT_STATE: FieldConditionalState = {
  visible: true,
  required: false,
  enabled: true,
  readOnly: false,
};

/**
 * Evaluate a predicate expression against a values map and return a
 * boolean. Rejects on parse error (returns fallback), so a bad predicate
 * never hides / disables a field silently.
 *
 * Reuses evaluateComputed's function-inlining trick so INTERACTION_FUNCTIONS
 * work here too (e.g. `contains(tags, "urgent")` or `age(dob) < 18`).
 */
export function evaluatePredicate(
  expr: string | undefined,
  values: Record<string, unknown>,
  fallback: boolean,
): boolean {
  if (!expr || typeof expr !== "string" || !expr.trim()) return fallback;
  try {
    const raw = evaluateComputed(expr.trim(), values);
    return Boolean(raw);
  } catch {
    return fallback;
  }
}

/**
 * For each field, compute its {visible, required, enabled, readOnly}
 * state from the four predicates. Missing predicates default to the
 * baseline (visible+enabled, not required, not readOnly). This is the
 * pure kernel — the React hook that drives re-render on values change
 * lives in @forge/library's Form.tsx.
 */
export function computeFieldConditionalStates(
  fields: Array<{ name: string; interaction?: FieldInteraction; required?: boolean; readOnly?: boolean; disabled?: boolean }>,
  values: Record<string, unknown>,
): Record<string, FieldConditionalState> {
  const out: Record<string, FieldConditionalState> = {};
  for (const f of fields) {
    if (!f || !f.name) continue;
    const inter = f.interaction ?? {};
    // Predicates OVERRIDE the static baseline when present, else fall
    // through to the field's own required/readOnly/disabled attrs.
    const visible = evaluatePredicate(inter.visibleIf, values, DEFAULT_STATE.visible);
    const required = inter.requiredIf
      ? evaluatePredicate(inter.requiredIf, values, false)
      : Boolean(f.required);
    const enabled = inter.enabledIf
      ? evaluatePredicate(inter.enabledIf, values, DEFAULT_STATE.enabled)
      : !f.disabled;
    const readOnly = inter.readOnlyIf
      ? evaluatePredicate(inter.readOnlyIf, values, false)
      : Boolean(f.readOnly);
    out[f.name] = { visible, required, enabled, readOnly };
  }
  return out;
}

// ── Whitelisted function library ────────────────────────────────────────────

/** Coerce anything to a finite number, or NaN when it isn't one. */
function num(x: unknown): number {
  if (x === null || x === undefined || x === "") return NaN;
  if (typeof x === "number") return x;
  if (x instanceof Date) return x.getTime();
  const n = Number(x);
  return n;
}

/** Coerce a date-ish (ISO string | Date | ms number) to a timestamp, or NaN. */
function toTime(x: unknown): number {
  if (x === null || x === undefined || x === "") return NaN;
  if (x instanceof Date) return x.getTime();
  if (typeof x === "number") return isNaN(x) ? NaN : x;
  const d = new Date(String(x));
  return d.getTime(); // NaN when unparseable
}

const MS_PER_DAY = 86_400_000;
const MS_PER_HOUR = 3_600_000;

/** Keep only the finite numbers from a coerced arg list. */
function finiteNums(args: unknown[]): number[] {
  const out: number[] = [];
  for (const a of args) {
    if (Array.isArray(a)) {
      out.push(...finiteNums(a));
      continue;
    }
    const n = num(a);
    if (typeof n === "number" && !isNaN(n) && isFinite(n)) out.push(n);
  }
  return out;
}

/**
 * The safe function library available to computed formulas. Every function is
 * total: it never throws, coerces string→number, and degrades to 0 / a skip on
 * missing or invalid input.
 */
export const INTERACTION_FUNCTIONS: Record<string, (...args: unknown[]) => unknown> = {
  /** Whole days from `a` (start) to `b` (end); 0 if either missing/invalid. */
  daysBetween: (a: unknown, b: unknown) => {
    const t0 = toTime(a);
    const t1 = toTime(b);
    if (isNaN(t0) || isNaN(t1)) return 0;
    return Math.round((t1 - t0) / MS_PER_DAY);
  },
  /** Whole hours from `a` (start) to `b` (end); 0 if either missing/invalid. */
  hoursBetween: (a: unknown, b: unknown) => {
    const t0 = toTime(a);
    const t1 = toTime(b);
    if (isNaN(t0) || isNaN(t1)) return 0;
    return Math.round((t1 - t0) / MS_PER_HOUR);
  },
  /** Sum of all finite numeric args (nested arrays flattened). */
  sum: (...args: unknown[]) => finiteNums(args).reduce((a, b) => a + b, 0),
  /** Min of finite numeric args; 0 when none are valid. */
  min: (...args: unknown[]) => {
    const ns = finiteNums(args);
    return ns.length ? Math.min(...ns) : 0;
  },
  /** Max of finite numeric args; 0 when none are valid. */
  max: (...args: unknown[]) => {
    const ns = finiteNums(args);
    return ns.length ? Math.max(...ns) : 0;
  },
  /** Round `n` to `digits` decimals (default 0). Invalid → 0. */
  round: (n: unknown, digits?: unknown) => {
    const x = num(n);
    if (isNaN(x)) return 0;
    const d = digits === undefined ? 0 : num(digits);
    const f = Math.pow(10, isNaN(d) ? 0 : d);
    return Math.round(x * f) / f;
  },
  /** Absolute value; invalid → 0. */
  abs: (n: unknown) => {
    const x = num(n);
    return isNaN(x) ? 0 : Math.abs(x);
  },
  /** Ceiling; invalid → 0. */
  ceil: (n: unknown) => {
    const x = num(n);
    return isNaN(x) ? 0 : Math.ceil(x);
  },
  /** Floor; invalid → 0. */
  floor: (n: unknown) => {
    const x = num(n);
    return isNaN(x) ? 0 : Math.floor(x);
  },
  /** Ternary: `cond` truthy → `a`, else `b`. */
  ifElse: (cond: unknown, a: unknown, b: unknown) => (cond ? a : b),

  // ── Slice 1 additions (2026-07-31) ────────────────────────────────────
  // All total, all defensive: never throw, coerce sensibly, degrade to
  // "" or 0 on invalid input. Mirrored in
  // backend/services/interaction_spec.py::KNOWN_FUNCTIONS.

  /** Coalesce: return the first argument that isn't null/undefined/"". */
  coalesce: (...args: unknown[]) => {
    for (const a of args) {
      if (a !== null && a !== undefined && a !== "") return a;
    }
    return "";
  },

  /** Numeric average of finite numeric args (nested arrays flattened). 0 if none. */
  avg: (...args: unknown[]) => {
    const ns = finiteNums(args);
    return ns.length ? ns.reduce((a, b) => a + b, 0) / ns.length : 0;
  },

  /** Count of args that aren't null/undefined/"" (nested arrays flattened). */
  count: (...args: unknown[]) => {
    let n = 0;
    const walk = (v: unknown) => {
      if (Array.isArray(v)) { for (const x of v) walk(x); return; }
      if (v !== null && v !== undefined && v !== "") n++;
    };
    for (const a of args) walk(a);
    return n;
  },

  /** x^y; invalid → 0. */
  pow: (x: unknown, y: unknown) => {
    const a = num(x); const b = num(y);
    if (isNaN(a) || isNaN(b)) return 0;
    return Math.pow(a, b);
  },

  /** Square root; invalid or negative → 0. */
  sqrt: (n: unknown) => {
    const x = num(n);
    return isNaN(x) || x < 0 ? 0 : Math.sqrt(x);
  },

  /** value / total × 100; total=0 or invalid → 0. */
  percent: (value: unknown, total: unknown) => {
    const v = num(value); const t = num(total);
    if (isNaN(v) || isNaN(t) || t === 0) return 0;
    return (v / t) * 100;
  },

  /** Clamp x to [lo, hi]; invalid → lo. */
  clamp: (x: unknown, lo: unknown, hi: unknown) => {
    const v = num(x); const l = num(lo); const h = num(hi);
    if (isNaN(v)) return isNaN(l) ? 0 : l;
    if (!isNaN(l) && v < l) return l;
    if (!isNaN(h) && v > h) return h;
    return v;
  },

  // ── Text helpers ──
  /** Concatenate any args stringified; null/undefined → "". */
  concat: (...args: unknown[]) => args.map((a) => (a === null || a === undefined) ? "" : String(a)).join(""),

  /** UPPERCASE, tolerating non-strings. */
  upper: (s: unknown) => String(s ?? "").toUpperCase(),
  /** lowercase, tolerating non-strings. */
  lower: (s: unknown) => String(s ?? "").toLowerCase(),
  /** Title Case (word-initial cap; simple, no locale). */
  title: (s: unknown) =>
    String(s ?? "").replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()),

  /** URL-safe slug: lowercase, spaces → dashes, strip non-alphanumeric. */
  slug: (s: unknown) =>
    String(s ?? "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, ""),

  /** Initials from a name: "John Adam Doe" → "JAD". Max 3 chars. */
  initials: (s: unknown) => {
    const parts = String(s ?? "").trim().split(/\s+/).filter(Boolean);
    return parts.slice(0, 3).map((p) => p.charAt(0).toUpperCase()).join("");
  },

  /** `haystack` contains `needle` (case-insensitive substring). */
  contains: (haystack: unknown, needle: unknown) =>
    String(haystack ?? "").toLowerCase().includes(String(needle ?? "").toLowerCase()),
  /** `str` starts with `prefix` (case-insensitive). */
  startsWith: (str: unknown, prefix: unknown) =>
    String(str ?? "").toLowerCase().startsWith(String(prefix ?? "").toLowerCase()),
  /** `str` ends with `suffix` (case-insensitive). */
  endsWith: (str: unknown, suffix: unknown) =>
    String(str ?? "").toLowerCase().endsWith(String(suffix ?? "").toLowerCase()),

  /** Regex test; false on invalid regex or non-string input. */
  matches: (str: unknown, pattern: unknown) => {
    try {
      const p = String(pattern ?? "");
      if (!p) return false;
      return new RegExp(p).test(String(str ?? ""));
    } catch { return false; }
  },

  // ── Date helpers ──
  /** Milliseconds since epoch — pure now(); ISO-safe when persisted. */
  now: () => Date.now(),
  /** Today at 00:00 (local) as timestamp. */
  today: () => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  },
  /** Whole years from `dob` to today; invalid → 0. */
  age: (dob: unknown) => {
    const t = toTime(dob);
    if (isNaN(t)) return 0;
    const d = new Date(t);
    const now = new Date();
    let years = now.getFullYear() - d.getFullYear();
    if (
      now.getMonth() < d.getMonth() ||
      (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())
    ) years--;
    return years < 0 ? 0 : years;
  },
  /** Whole years between two dates (a → b). */
  yearsBetween: (a: unknown, b: unknown) => {
    const t0 = toTime(a); const t1 = toTime(b);
    if (isNaN(t0) || isNaN(t1)) return 0;
    const d0 = new Date(t0); const d1 = new Date(t1);
    let years = d1.getFullYear() - d0.getFullYear();
    if (
      d1.getMonth() < d0.getMonth() ||
      (d1.getMonth() === d0.getMonth() && d1.getDate() < d0.getDate())
    ) years--;
    return years;
  },

  // ── Formatters (locale-aware where the runtime has it) ──
  /** ISO date string YYYY-MM-DD; invalid → "". */
  formatDate: (v: unknown, _fmt?: unknown) => {
    const t = toTime(v);
    if (isNaN(t)) return "";
    const d = new Date(t);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  },
  /** Localized currency; default USD. `currency` arg overrides. */
  formatCurrency: (v: unknown, currency: unknown = "USD") => {
    const n = num(v);
    if (isNaN(n)) return "";
    try {
      return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: String(currency || "USD"),
      }).format(n);
    } catch {
      return String(n);
    }
  },
  /** Thousands-separated integer/decimal; invalid → "". */
  formatNumber: (v: unknown, digits: unknown = 2) => {
    const n = num(v);
    if (isNaN(n)) return "";
    const d = Math.max(0, Math.min(20, Math.floor(num(digits) || 0)));
    try {
      return n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
    } catch {
      return String(n);
    }
  },
  /** Minimal phone formatter: strip non-digits, group with spaces. */
  formatPhone: (v: unknown) => {
    const raw = String(v ?? "").replace(/\D/g, "");
    if (!raw) return "";
    if (raw.length <= 4) return raw;
    if (raw.length <= 7) return `${raw.slice(0, raw.length - 4)} ${raw.slice(-4)}`;
    if (raw.length === 10) return `${raw.slice(0, 3)} ${raw.slice(3, 6)} ${raw.slice(6)}`;
    // Default: +ccc ddddd-ddddd style
    return `+${raw.slice(0, raw.length - 10)} ${raw.slice(-10, -5)}-${raw.slice(-5)}`;
  },

  // ── Calculator/keypad helpers (2026-07-31) ─────────────────────────────
  // Safe arithmetic-expression evaluation for calculator display strings.
  // Used by the deterministic computational-schema builder's "=" key:
  //   onClick: {kind:"compute", target:"display",
  //             formula:"evalExpression(display)"}
  // Whitelisted grammar: digits, `.`, `+`, `-`, `*`, `/`, `%`, `(`, `)`,
  // and unicode operator glyphs `×`, `÷`, `−`. Anything else → "Error".
  // Never uses `eval()` / `new Function()` — a hand-rolled shunting-yard
  // parser gives us guaranteed no-arbitrary-JS-execution.

  /** Safely evaluate a calculator display expression. Returns a numeric
   * string, or "Error" on invalid input / divide-by-zero / overflow. */
  evalExpression: (expr: unknown) => {
    const src = String(expr ?? "").trim();
    if (!src) return "";
    // Normalize unicode glyphs → ASCII operators
    const norm = src
      .replace(/×/g, "*")
      .replace(/÷/g, "/")
      .replace(/−/g, "-");
    // Whitelist: only digits/./operators/parens/space
    if (!/^[0-9.+\-*/%()\s]+$/.test(norm)) return "Error";
    // Tokenize
    const tokens: (string | number)[] = [];
    let i = 0;
    while (i < norm.length) {
      const ch = norm[i];
      if (ch === " ") { i++; continue; }
      if ("+-*/%()".includes(ch)) { tokens.push(ch); i++; continue; }
      if (/[0-9.]/.test(ch)) {
        let j = i + 1;
        while (j < norm.length && /[0-9.]/.test(norm[j])) j++;
        const n = Number(norm.slice(i, j));
        if (!isFinite(n)) return "Error";
        tokens.push(n);
        i = j;
        continue;
      }
      return "Error";
    }
    // Shunting-yard to RPN
    const prec: Record<string, number> = { "+": 1, "-": 1, "*": 2, "/": 2, "%": 2 };
    const output: (string | number)[] = [];
    const opstack: string[] = [];
    // Handle unary minus by tracking previous token.
    let prev: string | number | null = null;
    for (const tok of tokens) {
      if (typeof tok === "number") {
        output.push(tok);
        prev = tok;
        continue;
      }
      if (tok === "-" && (prev === null || (typeof prev === "string" && "+-*/%(".includes(prev)))) {
        // unary minus → push 0 first, treat as binary subtraction
        output.push(0);
        while (opstack.length && "+-*/%".includes(opstack[opstack.length - 1]) &&
               prec[opstack[opstack.length - 1]] >= prec["-"]) {
          output.push(opstack.pop()!);
        }
        opstack.push("-");
        prev = tok;
        continue;
      }
      if (tok === "(") { opstack.push(tok); prev = tok; continue; }
      if (tok === ")") {
        while (opstack.length && opstack[opstack.length - 1] !== "(") {
          output.push(opstack.pop()!);
        }
        if (!opstack.length) return "Error"; // unbalanced
        opstack.pop(); // discard "("
        prev = tok;
        continue;
      }
      if ("+-*/%".includes(tok)) {
        while (opstack.length && opstack[opstack.length - 1] !== "(" &&
               prec[opstack[opstack.length - 1]] >= prec[tok]) {
          output.push(opstack.pop()!);
        }
        opstack.push(tok);
        prev = tok;
      }
    }
    while (opstack.length) {
      const op = opstack.pop()!;
      if (op === "(") return "Error"; // unbalanced
      output.push(op);
    }
    // Evaluate RPN
    const stack: number[] = [];
    for (const tok of output) {
      if (typeof tok === "number") { stack.push(tok); continue; }
      if (stack.length < 2) return "Error";
      const b = stack.pop()!;
      const a = stack.pop()!;
      let r: number;
      switch (tok) {
        case "+": r = a + b; break;
        case "-": r = a - b; break;
        case "*": r = a * b; break;
        case "/": if (b === 0) return "Error"; r = a / b; break;
        case "%": if (b === 0) return "Error"; r = a % b; break;
        default: return "Error";
      }
      if (!isFinite(r)) return "Error";
      stack.push(r);
    }
    if (stack.length !== 1) return "Error";
    // Format: strip .0 tails, avoid scientific notation for typical calc range
    const result = stack[0];
    if (Math.abs(result) >= 1e15) return String(result);
    // Round tiny floating-point noise (e.g. 0.1+0.2)
    const rounded = Math.round(result * 1e10) / 1e10;
    return String(rounded);
  },
};

// Reserved words feel-lite / the grammar treat as non-variables.
const RESERVED = new Set([
  "true",
  "false",
  "null",
  "and",
  "or",
  "not",
  "if",
  "then",
  "else",
  "in",
  "between",
]);

// ── Formula variable extraction ─────────────────────────────────────────────

/** Strip string literals so their contents aren't mistaken for identifiers. */
function stripStrings(s: string): string {
  return s.replace(/'(?:[^'\\]|\\.)*'/g, " ").replace(/"(?:[^"\\]|\\.)*"/g, " ");
}

const IDENT_RE = /[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*/g;

/**
 * The identifier references in a formula that are NOT function names — i.e. the
 * fields the formula depends on. A name immediately followed by `(` is a call
 * and excluded; reserved words are excluded; string-literal contents ignored.
 * Dotted refs (`result.address`) collapse to their root (`result`). Order of
 * first appearance is preserved; duplicates removed.
 */
export function extractFormulaVars(formula: string): string[] {
  if (typeof formula !== "string" || !formula.trim()) return [];
  const src = stripStrings(formula);
  const out: string[] = [];
  const seen = new Set<string>();
  let m: RegExpExecArray | null;
  IDENT_RE.lastIndex = 0;
  while ((m = IDENT_RE.exec(src)) !== null) {
    const name = m[0];
    // Skip if this is a function call: next non-space char is "(".
    const after = src.slice(m.index + name.length).match(/^\s*/)?.[0].length ?? 0;
    if (src[m.index + name.length + after] === "(") continue;
    const root = name.split(".")[0];
    if (RESERVED.has(root)) continue;
    if (!seen.has(root)) {
      seen.add(root);
      out.push(root);
    }
  }
  return out;
}

// ── Computed formula evaluation ─────────────────────────────────────────────

/** Split an argument list on top-level commas (respecting parens/brackets/strings). */
function splitArgs(inner: string): string[] {
  const args: string[] = [];
  let depth = 0;
  let quote: string | null = null;
  let cur = "";
  for (let i = 0; i < inner.length; i++) {
    const ch = inner[i];
    if (quote) {
      cur += ch;
      if (ch === quote && inner[i - 1] !== "\\") quote = null;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      cur += ch;
      continue;
    }
    if (ch === "(" || ch === "[") depth++;
    else if (ch === ")" || ch === "]") depth--;
    if (ch === "," && depth === 0) {
      args.push(cur);
      cur = "";
      continue;
    }
    cur += ch;
  }
  if (cur.trim() !== "" || args.length > 0) args.push(cur);
  return args.map((a) => a.trim()).filter((a) => a.length > 0);
}

/** Does `inner` contain a call to any whitelisted interaction function? */
function hasInteractionCall(inner: string): boolean {
  const re = /([A-Za-z_$][\w$]*)\s*\(/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(inner)) !== null) {
    if (Object.prototype.hasOwnProperty.call(INTERACTION_FUNCTIONS, m[1])) return true;
  }
  return false;
}

/**
 * Locate the leftmost *innermost* whitelisted-function call in `expr`.
 * Returns its bounds + parsed argument strings, or null when none remain.
 */
function findInnermostCall(
  expr: string,
): { name: string; start: number; end: number; args: string[] } | null {
  const re = /([A-Za-z_$][\w$]*)\s*\(/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(expr)) !== null) {
    const name = m[1];
    if (!Object.prototype.hasOwnProperty.call(INTERACTION_FUNCTIONS, name)) continue;
    // Find the matching close paren for the "(" at end of this match.
    const openIdx = m.index + m[0].length - 1;
    let depth = 0;
    let quote: string | null = null;
    let closeIdx = -1;
    for (let i = openIdx; i < expr.length; i++) {
      const ch = expr[i];
      if (quote) {
        if (ch === quote && expr[i - 1] !== "\\") quote = null;
        continue;
      }
      if (ch === "'" || ch === '"') {
        quote = ch;
        continue;
      }
      if (ch === "(") depth++;
      else if (ch === ")") {
        depth--;
        if (depth === 0) {
          closeIdx = i;
          break;
        }
      }
    }
    if (closeIdx === -1) continue; // unbalanced — bail on this candidate
    const inner = expr.slice(openIdx + 1, closeIdx);
    // Innermost: its argument text must not itself contain a whitelisted call.
    if (hasInteractionCall(inner)) continue;
    return { name, start: m.index, end: closeIdx + 1, args: splitArgs(inner) };
  }
  return null;
}

/**
 * Evaluate a computed-field formula against `fieldValues`.
 *
 * The formula sees each sibling field as a variable AND the whitelisted
 * INTERACTION_FUNCTIONS as callable functions. Missing variables degrade to
 * 0 / empty (feel-lite already coerces `undefined`→0 in arithmetic); the call
 * never throws — a hard parse/eval failure returns `null`.
 *
 * Implementation reuses `evalExpression` (feel-lite): interaction-function
 * calls are resolved innermost-first to plain values bound to synthetic scope
 * variables (`__ifn0`, …), then the residual pure expression is handed to
 * feel-lite for the arithmetic / field-variable resolution.
 */
export function evaluateComputed(
  formula: string,
  fieldValues: Record<string, unknown>,
): unknown {
  if (typeof formula !== "string" || !formula.trim()) return null;
  try {
    const scope: Record<string, unknown> = { ...fieldValues };
    let expr = formula;
    let counter = 0;
    let guard = 0;
    // Resolve every interaction-function call to a value (innermost-first).
    while (guard++ < 1000) {
      const call = findInnermostCall(expr);
      if (!call) break;
      const argValues = call.args.map((a) => evalExpression(a, scope));
      const fn = INTERACTION_FUNCTIONS[call.name];
      let value: unknown;
      try {
        value = fn(...argValues);
      } catch {
        value = 0;
      }
      const sym = `__ifn${counter++}`;
      scope[sym] = value;
      expr = expr.slice(0, call.start) + sym + expr.slice(call.end);
    }
    const result = evalExpression(expr, scope);
    // evalExpression returns `false` as its hard-error sentinel; a computed
    // numeric formula never legitimately yields boolean false, so map it null.
    if (result === false && !/\b(true|false|=|<|>|and|or|not)\b/.test(formula)) {
      return null;
    }
    return result;
  } catch {
    return null;
  }
}

// ── Computed dependency ordering ─────────────────────────────────────────────

/**
 * Topologically order computed fields so each is evaluated after the computed
 * fields its formula references. Cycle-safe: on a dependency cycle the cycle is
 * broken deterministically (input order) so the function always terminates and
 * returns every computed field exactly once.
 */
export function computedEvalOrder(
  fields: { name: string; interaction?: FieldInteraction }[],
): string[] {
  // Computed fields, in declaration order.
  const computed = fields.filter((f) => f.interaction?.computed?.formula);
  const names = computed.map((f) => f.name);
  const nameSet = new Set(names);

  // Dependency edges among computed fields: dep → field (dep evaluated first).
  const deps = new Map<string, Set<string>>();
  const indegree = new Map<string, number>();
  for (const n of names) {
    deps.set(n, new Set());
    indegree.set(n, 0);
  }
  for (const f of computed) {
    const vars = extractFormulaVars(f.interaction!.computed!.formula);
    for (const v of vars) {
      if (v !== f.name && nameSet.has(v) && !deps.get(v)!.has(f.name)) {
        deps.get(v)!.add(f.name);
        indegree.set(f.name, indegree.get(f.name)! + 1);
      }
    }
  }

  const order: string[] = [];
  const done = new Set<string>();
  while (order.length < names.length) {
    // Pick the declaration-order-first not-yet-emitted node with indegree 0.
    let pick: string | undefined = names.find(
      (n) => !done.has(n) && indegree.get(n) === 0,
    );
    // Cycle: nothing at indegree 0 — break it by taking the first remaining
    // node deterministically.
    if (pick === undefined) {
      pick = names.find((n) => !done.has(n));
    }
    if (pick === undefined) break;
    order.push(pick);
    done.add(pick);
    for (const dependent of deps.get(pick)!) {
      if (!done.has(dependent)) {
        indegree.set(dependent, Math.max(0, indegree.get(dependent)! - 1));
      }
    }
  }
  return order;
}
