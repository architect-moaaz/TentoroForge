/**
 * The workflow `decision` step: a decision table, or a business rule of the
 * app, run over the workflow's data.
 *
 * Two ways to say what it runs:
 *   config.decisionTable   a table written into the step itself;
 *   config.rule            a business rule of the app, by id (RULE-012): a
 *                          decision table's outputs, or a condition rule's
 *                          yes/no — the same rule that guards the record on
 *                          every save, kept in one place.
 *
 * Cells, hit policies and matching are `rules/decision-table.ts` — the one
 * implementation the app's save path and the platform's editor use too.
 *
 * The step BRANCHES: `matched` is true when a row matched (a table), when a
 * rule that can refuse lets the data through, or — for a rule that never
 * refuses — when its condition held; the engine takes the then-path, or the
 * else-path when it is false. Outputs are written into the workflow's
 * variables, renamed by `outputMapping` when one is given.
 */
import { evaluateExpression } from "../feel-lite";
import {
  evaluateTable, normalizeHitPolicy, parseCell, matchConstraint, outputValue,
  type DecisionTableDef,
} from "../rules/decision-table";

export interface DecisionNodeConfig {
  decisionTable?: DecisionTableDef;
  outputMapping?: Record<string, string>;
  /** A business rule of the app, by id. */
  rule?: string;
}

export interface DecisionContext {
  variables: Record<string, unknown>;
}

/** A rule of the app as its rules file holds it (see rules/types ProjectRule). */
export interface RuleRow {
  id?: string;
  name?: string;
  rule_type?: string;
  /** The record it is about (Expense): where its fields are found in a run. */
  model_name?: string | null;
  is_active?: boolean;
  config?: Record<string, unknown>;
}

export interface DecisionResult {
  /** How many rows' outputs were used (a table), or 1/0 (a condition rule). */
  fired: number;
  /** The table's hit policy as a word: first, unique, priority, any, collect, rule order. */
  hitPolicy: string;
  /** The values written. Under collect without aggregation, one object per matched row. */
  outputs: Record<string, unknown> | Array<Record<string, unknown>>;
  /** Did a row match / did the condition hold — the step's branch. */
  matched: boolean;
  /** 1-based rows that matched. */
  rows?: number[];
  violation?: string;
  rule?: string;
  message?: string;
  skipped?: boolean;
  reason?: string;
}

const WORD: Record<string, string> = { U: "unique", F: "first", P: "priority", A: "any", C: "collect", R: "rule order" };

function write(ctx: DecisionContext, outputs: Record<string, unknown>, mapping: Record<string, string>) {
  for (const [name, val] of Object.entries(outputs)) {
    if (val === undefined) continue;
    ctx.variables[mapping[name] || name] = val;
  }
}

/**
 * The rule's record inside a run. A rule reads its record's fields by name
 * (`amount`); a workflow often carries the record as one variable
 * (`expense.amount`, after a load step or from the screen that started it).
 * The record is the variable named for it — expense, Expense, expense_item —
 * or `record`; with none, the fields are the run's own variables.
 */
export function recordIn(vars: Record<string, unknown>, model?: string | null): Record<string, unknown> | null {
  const m = String(model || "").trim();
  const names = m ? [m.charAt(0).toLowerCase() + m.slice(1), m, m.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase()] : [];
  for (const n of [...names, "record"]) {
    const v = vars[n];
    if (v && typeof v === "object" && !Array.isArray(v)) return v as Record<string, unknown>;
  }
  return null;
}

/** What a rule sees: the run's variables, with its record's fields by name on top. */
function scopeFor(ctx: DecisionContext, record: Record<string, unknown> | null): Record<string, unknown> {
  return record ? { ...ctx.variables, ...record } : ctx.variables;
}

/** A value a rule sets is the record's too, so the steps after it see `expense.managerNote`. */
function writeRecord(record: Record<string, unknown> | null, outputs: Record<string, unknown>) {
  if (!record) return;
  for (const [name, val] of Object.entries(outputs)) if (val !== undefined) record[name] = val;
}

function runTable(table: DecisionTableDef, ctx: DecisionContext, mapping: Record<string, string>,
                  record: Record<string, unknown> | null = null): DecisionResult {
  const policy = normalizeHitPolicy(table.hitPolicy);
  const vars = scopeFor(ctx, record);
  const r = evaluateTable(table, vars);
  let outputs: DecisionResult["outputs"] = r.outputs;
  // Collect without an aggregation: one outcome per matched row, as before.
  if (policy === "C" && !table.aggregation) {
    outputs = r.used.map((ri) => {
      const o: Record<string, unknown> = {};
      (table.outputs || []).forEach((col, ci) => {
        const v = outputValue((table.rules || [])[ri]?.outputEntries?.[ci], vars);
        if (v !== undefined) o[String(col.variableBinding || col.name)] = v;
      });
      return o;
    });
    if (outputs.length) { write(ctx, outputs[0], mapping); writeRecord(record, outputs[0]); }
  } else {
    write(ctx, r.outputs, mapping);
    writeRecord(record, r.outputs);
  }
  return {
    fired: r.used.length,
    hitPolicy: WORD[policy],
    outputs,
    matched: r.matched.length > 0,
    rows: r.matched.map((i) => i + 1),
    ...(r.violation ? { violation: r.violation } : {}),
  };
}

/**
 * Run the step. `rule` is the app's rule named by `config.rule`, looked up by
 * the caller (the engine reads the app's rules files). A step naming a rule
 * that is gone is skipped and takes the else-path — it never passes as if the
 * rule had said yes; a rule switched off does not apply, so the run goes on.
 */
export function evaluateDecision(
  config: DecisionNodeConfig,
  ctx: DecisionContext,
  rule?: RuleRow | null,
): DecisionResult {
  const mapping = (config.outputMapping || {}) as Record<string, string>;
  if (config.rule) {
    if (!rule) {
      return { fired: 0, hitPolicy: "first", outputs: {}, matched: false, skipped: true, rule: config.rule,
               reason: `the business rule ${config.rule} is not in this app` };
    }
    // Switched off is "the rule does not apply" — on a save and here alike:
    // the step lets the run through. (Gone is different: a broken
    // definition, which never passes as a yes.)
    if (rule.is_active === false) {
      return { fired: 0, hitPolicy: "first", outputs: {}, matched: true, skipped: true, rule: config.rule,
               reason: `the business rule ${rule.name || config.rule} is switched off` };
    }
    const cfg = (rule.config || {}) as Record<string, any>;
    const record = recordIn(ctx.variables, rule.model_name);
    if (rule.rule_type === "decision_table" && cfg.table) {
      return { ...runTable(cfg.table as DecisionTableDef, ctx, mapping, record), rule: config.rule };
    }
    const vars = scopeFor(ctx, record);
    // A condition rule: its condition is the branch; a value it sets is
    // written for the steps after; its refusal message travels with the run.
    let held = false;
    try {
      held = Boolean(evaluateExpression(String(cfg.whenFeel || "true"), vars as any));
    } catch (err) {
      throw new Error(`[decision] the condition of ${rule.name || config.rule} could not be read: ${(err as Error).message}`);
    }
    const acts = (held ? cfg.then : cfg.otherwise) as Array<Record<string, unknown>> | undefined;
    // A rule that can refuse is a GATE: its then-path is "the rule lets it
    // through" and its else-path "the rule refuses" — whichever side of the
    // condition the refusal is written on ("when over 5000 and no note:
    // refuse" refuses when its condition HOLDS). A rule that never refuses
    // branches on its condition.
    // A field the rule requires stops the run when it is blank, as it stops
    // the save ("above 5000, a manager note is required").
    const blank = (v: unknown) => v === null || v === undefined || (typeof v === "string" && v.trim() === "");
    const stopper = (a: any) => a?.type === "show_error" || (a?.type === "set_required" && a?.required !== false);
    const refuses = (list: unknown) => Array.isArray(list) && list.some(stopper);
    const isGate = refuses(cfg.then) || refuses(cfg.otherwise);
    const refusedNow = Array.isArray(acts) && acts.some((a: any) =>
      a?.type === "show_error" || (a?.type === "set_required" && a?.required !== false && a?.field && blank(vars[a.field])));
    const outputs: Record<string, unknown> = {};
    let message: string | undefined;
    for (const a of acts || []) {
      if ((a.type === "set_field" || a.type === "set_default") && a.field) {
        if (a.type === "set_default" && vars[a.field as string] != null && vars[a.field as string] !== "") continue;
        outputs[a.field as string] = a.valueMode === "formula" || a.valueMode === "field"
          ? evaluateExpression(String(a.value ?? ""), vars as any)
          : outputValue(a.value, {});
      }
      if (a.type === "show_error" && a.message) message = String(a.message);
      if (a.type === "set_required" && a.required !== false && a.field && blank(vars[a.field as string]) && !message)
        message = String(a.message || `${a.field} is required.`);
    }
    write(ctx, outputs, mapping);
    writeRecord(record, outputs);
    const passes = isGate ? !refusedNow : held;
    return { fired: held ? 1 : 0, hitPolicy: "first", outputs, matched: passes, rule: config.rule,
             ...(message && refusedNow ? { message } : {}) };
  }
  const table = config.decisionTable;
  if (!table || !Array.isArray(table.inputs) || !Array.isArray(table.rules)) {
    return { fired: 0, hitPolicy: "first", outputs: {}, matched: false, skipped: true, reason: "no decision table" };
  }
  return runTable(table, ctx, mapping);
}

/** One input cell against one value — kept for callers of the old matcher. */
export function matchesEntry(value: unknown, entry: string): boolean {
  const p = parseCell(entry);
  return p.ok ? matchConstraint(p.constraint!, value) : false;
}

/** An output cell's literal value — kept for callers of the old matcher. */
export function coerceLiteral(raw: unknown): unknown {
  if (typeof raw !== "string") return raw;
  return outputValue(raw, {});
}
