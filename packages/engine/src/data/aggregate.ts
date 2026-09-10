/**
 * Compute an `op:"aggregate"` dataSource's metrics from rows.
 *
 * WHY THIS LIVES IN THE ENGINE
 * ----------------------------
 * Three surfaces render the same page schema and each answered "what is a KPI
 * metric?" differently, which is how a correctly-declared tile ended up blank:
 *
 *   - the EDITOR canvas (`frontend/src/lib/preview-resolve.ts`) COMPUTES the
 *     metric from fixture rows, so KPI tiles showed numbers there;
 *   - the SCAFFOLD (`apps/render-scaffold/src/lib/resolvePreviewSync.ts`) only
 *     LOOKED UP a pre-computed `<entity>Stats` object and fell back to `{}`,
 *     so the very same page rendered three empty tiles in the shipped preview;
 *   - the generated app's data engine compiles `{fn, field}` to SQL.
 *
 * Nothing was wrong with the schema by the time it got here — the source was
 * named correctly and the metrics were normalised. The value was simply never
 * calculated. So the calculation belongs in one place that every surface can
 * import, which is this package.
 *
 * It deliberately understands BOTH metric dialects. `{fn, field}` is the
 * runtime contract; `{expression: "sum(quantity * price)"}` is what the page
 * composer writes. The generator normalises the latter away now, but projects
 * already on disk still carry it and may never be regenerated.
 */

export interface AggregateMetric {
  fn?: string;
  field?: string;
  /** Arithmetic over several columns, e.g. `"quantity * price"`. */
  expr?: string;
  /** The composer's dialect, e.g. `"sum(quantity * price)"`. */
  expression?: string;
  entity?: string;
  filter?: Record<string, unknown>;
}

export interface AggregateSource {
  name: string;
  entity?: string;
  op?: string;
  metrics?: Record<string, AggregateMetric>;
  filter?: Record<string, unknown>;
}

const norm = (s: string) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");

const toNum = (v: unknown): number => {
  const n = Number(v);
  return isNaN(n) ? 0 : n;
};

/**
 * Find an entity's rows across the key aliases a fixture endpoint emits
 * (`Vehicle` | `vehicle` | `vehicles` | …).
 */
export function rowsFor(entity: string | undefined, data: Record<string, unknown>): any[] {
  if (!entity) return [];
  if (Array.isArray(data[entity])) return data[entity] as any[];
  const want = norm(entity);
  for (const [k, v] of Object.entries(data)) {
    if (!Array.isArray(v)) continue;
    const nk = norm(k);
    if (nk === want || nk === want + "s" || nk + "s" === want) return v as any[];
  }
  return [];
}

export function matchesFilter(row: any, filter?: Record<string, unknown>): boolean {
  if (!filter) return true;
  return Object.entries(filter).every(([k, v]) => {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      // Comparator form: { quantity: { lt: 5 } }
      return Object.entries(v as Record<string, unknown>).every(([op, operand]) => {
        const cell = row?.[k];
        switch (op) {
          case "lt": return toNum(cell) < toNum(operand);
          case "lte": return toNum(cell) <= toNum(operand);
          case "gt": return toNum(cell) > toNum(operand);
          case "gte": return toNum(cell) >= toNum(operand);
          case "ne": return cell !== operand;
          case "eq": return cell === operand;
          default: return true;
        }
      });
    }
    return row?.[k] === v;
  });
}

/**
 * Evaluate `+ - * / ( )` arithmetic over one row's fields. Recursive descent,
 * NOT `eval` and NOT `new Function` — a page schema is data, and data must not
 * become code just because a KPI tile needed the product of two columns.
 * Anything unparseable yields NaN, which `toNum` folds to 0.
 */
export function evalExpr(expr: string, row: any): number {
  const tokens = expr.match(/[A-Za-z_][A-Za-z0-9_.]*|\d+(?:\.\d+)?|[()+\-*/]/g);
  // Every character must belong to a token; a stray quote or call means this is
  // a dialect we do not speak, and guessing would invent a number.
  if (!tokens || tokens.join("") !== expr.replace(/\s+/g, "")) return NaN;
  let i = 0;
  const peek = () => tokens[i];
  const expression = (): number => {
    let v = term();
    while (peek() === "+" || peek() === "-") {
      const op = tokens[i++];
      v = op === "+" ? v + term() : v - term();
    }
    return v;
  };
  const term = (): number => {
    let v = factor();
    while (peek() === "*" || peek() === "/") {
      const op = tokens[i++];
      const r = factor();
      // Division by zero is not a number a tile can show; 0 is the answer every
      // other failure here gives.
      v = op === "*" ? v * r : r === 0 ? 0 : v / r;
    }
    return v;
  };
  const factor = (): number => {
    const t = tokens[i];
    if (t === undefined) return NaN;
    if (t === "-") { i++; return -factor(); }
    if (t === "(") {
      i++;
      const v = expression();
      if (tokens[i] !== ")") return NaN;
      i++;
      return v;
    }
    i++;
    if (/^[A-Za-z_]/.test(t)) {
      return toNum(t.split(".").reduce((o: any, k) => (o == null ? o : o[k]), row));
    }
    return Number(t);
  };
  const value = expression();
  return i === tokens.length ? value : NaN;
}

/**
 * `"sum(quantity * price)"` → `{fn:"sum", expr:"quantity * price"}`.
 * Returns null for anything that is not an aggregate call, so the caller keeps
 * whatever the metric already said.
 */
export function parseExpression(
  expression?: string,
): { fn: string; field?: string; expr?: string } | null {
  if (typeof expression !== "string") return null;
  const m = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(([\s\S]*)\)\s*$/.exec(expression.trim());
  if (!m) return null;
  const alias: Record<string, string> = {
    count: "count", sum: "sum", total: "sum", avg: "avg", average: "avg",
    mean: "avg", min: "min", minimum: "min", max: "max", maximum: "max",
  };
  const fn = alias[m[1].toLowerCase()];
  if (!fn) return null;
  const arg = m[2].trim().replace(/^distinct\s+/i, "").trim();
  // count(id) / count(*) are row counts; treating `id` as a summable field
  // would give 0.
  if (fn === "count") return { fn: "count" };
  if (!arg) return null;
  if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(arg)) return { fn, field: arg };
  return { fn, expr: arg };
}

export function aggValue(
  rows: any[], fn: string | undefined, field?: string, expr?: string,
): number {
  if (fn === "count" || (!field && !expr)) return rows.length;
  const nums = expr
    ? rows.map((r) => toNum(evalExpr(expr, r)))
    : rows.map((r) => toNum(r?.[field!]));
  if (!nums.length) return 0;
  switch (fn) {
    case "sum": return nums.reduce((a, b) => a + b, 0);
    case "avg": return Math.round((nums.reduce((a, b) => a + b, 0) / nums.length) * 100) / 100;
    case "min": return Math.min(...nums);
    case "max": return Math.max(...nums);
    default: return rows.length;
  }
}

/**
 * Resolve every metric on an aggregate source against `data`.
 * Returns `{ [metricKey]: number }` — the shape a `{{source.metric}}` binding
 * expects. Never throws: an unusable metric contributes 0, not an exception.
 */
export function computeAggregate(
  source: AggregateSource,
  data: Record<string, unknown>,
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [key, m] of Object.entries(source.metrics || {})) {
    try {
      const rows = rowsFor(m?.entity || source.entity, data)
        .filter((r) => matchesFilter(r, m?.filter ?? source.filter));
      // A machine-readable `fn` wins; `expression` is read only when the metric
      // carries no usable one, so a normalised metric is never second-guessed.
      const spec = m?.fn ? m : { ...m, ...(parseExpression(m?.expression) || {}) };
      out[key] = aggValue(rows, spec.fn, spec.field, spec.expr);
    } catch {
      out[key] = 0;
    }
  }
  return out;
}
