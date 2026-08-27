import { evalExpression } from "./bindings";

/**
 * Mustache-style template interpolation. Replaces `{{expression}}` patterns in
 * a string with the result of evaluating `expression` against `data`. Used to
 * resolve schema content like:
 *
 *   "Welcome, {{user.name}}!" + { user: { name: "Sarah" } }  → "Welcome, Sarah!"
 *
 * Why this exists: the schema-generation LLM consistently emits Mustache-style
 * templates inside Text/Heading content, Hero headlines, etc. The v2 schema
 * spec doesn't formally support this — bindings are supposed to flow via the
 * `bind` field — but every project's schemas have these literals on disk and
 * rewriting them all isn't realistic. Resolving them at render time gives the
 * intended behaviour without changing schema files.
 *
 * Behaviour:
 *   - Strings without `{{...}}` are returned verbatim.
 *   - Each `{{expression}}` is evaluated independently. If the expression
 *     evaluates to undefined / null / false, the placeholder is dropped from
 *     the output. (False is filtered to avoid the literal "false" leaking
 *     into UI when an expression silently fails — the existing evalExpression
 *     contract returns false for binding failures.)
 *   - Numbers / strings / booleans render as their string form.
 *   - Objects / arrays render as JSON for debuggability.
 *   - Calls evalExpression — the same function used by visibleIf — so the
 *     expression syntax is identical to what node.visibleIf already accepts.
 */
const TEMPLATE_RE = /\{\{\s*([^{}]+?)\s*\}\}/g;
const WHOLE_TEMPLATE_RE = /^\s*\{\{\s*([^{}]+?)\s*\}\}\s*$/;

/**
 * IRF-M6-T7 — formatter modifier syntax.
 *
 * Supports `{{expression | formatter[:arg]}}`:
 *   {{growth | percent}}          → "12%"          (accepts 0.12 or 12)
 *   {{growth | percent:1}}        → "12.3%"
 *   {{price | currency}}          → "$1,234.56"
 *   {{price | currency:EUR}}      → "€1,234.56"
 *   {{createdAt | relative}}      → "3 days ago"
 *   {{count | number}}            → "1,234"
 *
 * Splits at the LAST `|` so nested pipe-shaped expressions stay parseable.
 * An unknown formatter is treated as no-op (the raw evaluated value flows
 * through), so the change is safe for pre-formatter schemas.
 */
function splitFormatter(expr: string): { source: string; formatter?: string; arg?: string } {
  const idx = expr.lastIndexOf("|");
  if (idx === -1) return { source: expr };
  const source = expr.slice(0, idx).trim();
  const spec = expr.slice(idx + 1).trim();
  if (!spec || !/^[a-zA-Z_][\w-]*(?::.*)?$/.test(spec)) return { source: expr };
  const [name, ...rest] = spec.split(":");
  return { source, formatter: name.trim(), arg: rest.join(":").trim() || undefined };
}

function applyFormatter(value: unknown, formatter: string, arg?: string): unknown {
  if (value === undefined || value === null || value === false) return "";
  switch (formatter) {
    case "percent": {
      const n = typeof value === "number" ? value : parseFloat(String(value));
      if (Number.isNaN(n)) return String(value);
      const digits = arg ? parseInt(arg, 10) : 0;
      // Heuristic: values in [-1, 1] are fractions (0.12 → 12%), others literal (12 → 12%)
      const pct = Math.abs(n) <= 1 ? n * 100 : n;
      return `${pct.toFixed(Number.isNaN(digits) ? 0 : digits)}%`;
    }
    case "currency": {
      const n = typeof value === "number" ? value : parseFloat(String(value));
      if (Number.isNaN(n)) return String(value);
      const cur = (arg || "USD").toUpperCase();
      try {
        return new Intl.NumberFormat(undefined, {
          style: "currency", currency: cur,
        }).format(n);
      } catch {
        return `${cur} ${n.toFixed(2)}`;
      }
    }
    case "number": {
      const n = typeof value === "number" ? value : parseFloat(String(value));
      if (Number.isNaN(n)) return String(value);
      const digits = arg ? parseInt(arg, 10) : 0;
      return new Intl.NumberFormat(undefined, {
        maximumFractionDigits: Number.isNaN(digits) ? 0 : digits,
      }).format(n);
    }
    case "relative": {
      const t = value instanceof Date ? value.getTime() : Date.parse(String(value));
      if (Number.isNaN(t)) return String(value);
      const diff = (t - Date.now()) / 1000;
      const abs = Math.abs(diff);
      const rtf = typeof Intl !== "undefined" && (Intl as any).RelativeTimeFormat
        ? new (Intl as any).RelativeTimeFormat(undefined, { numeric: "auto" })
        : null;
      const format = (val: number, unit: string) => rtf
        ? rtf.format(Math.round(val), unit)
        : `${Math.abs(Math.round(val))} ${unit}${Math.abs(val) === 1 ? "" : "s"} ${val < 0 ? "ago" : "from now"}`;
      if (abs < 60) return format(diff, "second");
      if (abs < 3600) return format(diff / 60, "minute");
      if (abs < 86400) return format(diff / 3600, "hour");
      if (abs < 604800) return format(diff / 86400, "day");
      if (abs < 2629800) return format(diff / 604800, "week");
      if (abs < 31557600) return format(diff / 2629800, "month");
      return format(diff / 31557600, "year");
    }
    default:
      return value;
  }
}

/**
 * Interpolate Mustache placeholders in `text`.
 *
 * If the entire input is a single `{{expr}}` template, the result is the raw
 * evaluated value (any type) — so a number-typed schema field bound to
 * `"{{count}}"` resolves to a real number rather than its string form, and
 * downstream Zod validation that expects `z.number()` accepts it. The return
 * type is `unknown` to reflect this; consumers that always want a string
 * should call `interpolate()` from a string-context branch.
 *
 * For mixed input (e.g. `"Hi {{name}}!"` ) the result is a string with each
 * placeholder substituted, dropping unresolved expressions.
 */
export function interpolate(text: string, data: Record<string, unknown>): unknown {
  if (typeof text !== "string" || text.indexOf("{{") === -1) return text;
  // Whole-string template — preserve the value's native type when it
  // resolves. When it doesn't (no data context, e.g. editor preview), keep
  // the literal template string so required string fields still validate
  // (the user sees the placeholder text, layout doesn't break). The previous
  // undefined-on-unresolved behaviour drops the key from the parent and
  // crashes validation for required fields.
  const whole = text.match(WHOLE_TEMPLATE_RE);
  if (whole) {
    const rawExpr = whole[1].trim();
    // IRF-M6-T7: `{{expr | formatter[:arg]}}` — split then eval.
    const { source, formatter, arg } = splitFormatter(rawExpr);
    const expr = source;
    const rawValue = evalExpression(expr, data);
    const v = formatter ? applyFormatter(rawValue, formatter, arg) : rawValue;
    if (v === undefined || v === null || v === false) {
      // Live render: when the binding's ROOT source is present in the data
      // context (e.g. a Repeat row `item`, or a resolved dataSource) but the
      // path didn't resolve — typically a field that doesn't exist on the row —
      // render empty rather than leaking the raw `{{…}}` placeholder to users.
      // Only the editor/preview canvas (no data context at all) keeps the
      // placeholder visible so authors can see what's bound.
      const root = expr.match(/^([A-Za-z_$][\w$]*)/)?.[1];
      if (root && Object.prototype.hasOwnProperty.call(data, root)) return "";
      return text;
    }
    return v;
  }
  // Mixed text + templates — string substitution as before.
  return text.replace(TEMPLATE_RE, (_match, rawExpr: string) => {
    const { source, formatter, arg } = splitFormatter(rawExpr.trim());
    const raw = evalExpression(source, data);
    const v = formatter ? applyFormatter(raw, formatter, arg) : raw;
    if (v === undefined || v === null || v === false) return "";
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
    try { return JSON.stringify(v); } catch { return ""; }
  });
}

/**
 * Recursively walk an arbitrary value (object/array/primitive) and run
 * `interpolate` on every string. Returns a NEW value with interpolated
 * results. Whole-string templates that resolve to non-strings keep their
 * native type (so e.g. delta.value: "{{growth}}" against {growth: 0.15}
 * becomes the number 0.15, not the string "0.15"). When a whole-string
 * template can't resolve, the key is dropped from the parent object so
 * downstream schema validation sees an absent value (likely an
 * `.optional()` field) rather than an empty string that fails type checks.
 */
export function interpolateDeep(value: unknown, data: Record<string, unknown>): unknown {
  if (typeof value === "string") return interpolate(value, data);
  if (Array.isArray(value)) {
    // Drop array elements that interpolate to undefined.
    const out: unknown[] = [];
    for (const v of value) {
      const r = interpolateDeep(v, data);
      if (r !== undefined) out.push(r);
    }
    return out;
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      const r = interpolateDeep(v, data);
      if (r !== undefined) out[k] = r;
    }
    return out;
  }
  return value;
}
