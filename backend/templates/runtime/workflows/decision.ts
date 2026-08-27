/**
 * Rule-table evaluation for the `decision` node.
 *
 * Tentoro's own rule-table syntax (not DMN — see the plan doc). A rule
 * fires when every one of its inputEntries matches the corresponding
 * input variable's current value. Supported entry syntax:
 *
 *   -  / ""       wildcard — always matches
 *   "foo" / foo   equality on stringified value
 *   > N / >= N    numeric compare (also < / <= / !=)
 *   [a..b]        inclusive numeric range
 *
 * When a rule fires, each outputEntry is coerced ("42" → 42, "true" →
 * true) and written under the corresponding output name. Optional
 * `outputMapping` renames outputs before write (grade → letter).
 *
 * Hit policy:
 *   "first"   → stop at first match (default)
 *   "unique"  → same as first (spec-lint only)
 *   "collect" → evaluate every rule, return `outcomes[]`
 *
 * Pure — no db, no drizzle, no @/* imports. Extracted from engine.ts so
 * the standalone Vitest-free harness can exercise it directly.
 */

export interface DecisionNodeConfig {
  decisionTable?: {
    inputs: Array<{ name: string; variableBinding?: string; type?: string }>;
    outputs: Array<{ name: string; type?: string }>;
    rules: Array<{ inputEntries: string[]; outputEntries: string[] }>;
    hitPolicy?: string;
  };
  outputMapping?: Record<string, string>;
}

export interface DecisionContext {
  variables: Record<string, unknown>;
}

export interface DecisionResult {
  fired: number;
  hitPolicy: string;
  outputs: Record<string, unknown> | Array<Record<string, unknown>>;
  skipped?: boolean;
  reason?: string;
}

export function evaluateDecision(
  config: DecisionNodeConfig,
  ctx: DecisionContext,
): DecisionResult {
  const table = config.decisionTable;
  if (!table || !Array.isArray(table.inputs) || !Array.isArray(table.rules)) {
    return { fired: 0, hitPolicy: "first", outputs: {}, skipped: true, reason: "no decision table" };
  }
  const outputMapping = (config.outputMapping || {}) as Record<string, string>;
  const hitPolicy: string = (table.hitPolicy || "first").toLowerCase();

  const inputValues = table.inputs.map((inp) => {
    if (inp?.variableBinding && inp.variableBinding in ctx.variables) {
      return ctx.variables[inp.variableBinding];
    }
    return ctx.variables[inp?.name];
  });

  const outcomes: Array<Record<string, unknown>> = [];
  for (const rule of table.rules) {
    const entries = rule.inputEntries || [];
    let allMatch = true;
    for (let i = 0; i < table.inputs.length; i++) {
      const entry = String(entries[i] ?? "").trim();
      if (!matchesEntry(inputValues[i], entry)) { allMatch = false; break; }
    }
    if (!allMatch) continue;
    const produced: Record<string, unknown> = {};
    for (let j = 0; j < table.outputs.length; j++) {
      const outName = table.outputs[j].name;
      const raw = (rule.outputEntries || [])[j];
      produced[outName] = coerceLiteral(raw);
    }
    outcomes.push(produced);
    if (hitPolicy === "first" || hitPolicy === "unique") break;
  }

  const winner = outcomes[0] ?? {};
  for (const [outName, val] of Object.entries(winner)) {
    const target = outputMapping[outName] || outName;
    ctx.variables[target] = val;
  }

  return {
    fired: outcomes.length,
    hitPolicy,
    outputs: hitPolicy === "collect" ? outcomes : winner,
  };
}

export function matchesEntry(value: unknown, entry: string): boolean {
  const e = entry.trim();
  if (e === "" || e === "-" || e === "*") return true;

  const rangeM = e.match(/^\[\s*(-?\d+(?:\.\d+)?)\s*\.\.\s*(-?\d+(?:\.\d+)?)\s*\]$/);
  if (rangeM) {
    const n = Number(value);
    return !Number.isNaN(n) && n >= Number(rangeM[1]) && n <= Number(rangeM[2]);
  }
  const cmpM = e.match(/^(>=|<=|!=|>|<)\s*(-?\d+(?:\.\d+)?)$/);
  if (cmpM) {
    const n = Number(value);
    const rhs = Number(cmpM[2]);
    if (Number.isNaN(n)) return false;
    switch (cmpM[1]) {
      case ">":  return n >  rhs;
      case ">=": return n >= rhs;
      case "<":  return n <  rhs;
      case "<=": return n <= rhs;
      case "!=": return n !== rhs;
    }
  }
  const quoted = e.match(/^"(.*)"$|^'(.*)'$/);
  const literal = quoted ? (quoted[1] ?? quoted[2]) : e;
  return String(value) === literal;
}

export function coerceLiteral(raw: unknown): unknown {
  if (typeof raw !== "string") return raw;
  const s = raw.trim();
  const q = s.match(/^"(.*)"$|^'(.*)'$/);
  if (q) return q[1] ?? q[2];
  if (s === "true") return true;
  if (s === "false") return false;
  if (s === "null") return null;
  if (/^-?\d+(?:\.\d+)?$/.test(s)) return Number(s);
  return s;
}
