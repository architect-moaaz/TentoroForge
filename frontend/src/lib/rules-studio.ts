// ---------------------------------------------------------------------------
// The Business Rules studio: what the server answers beyond a rule itself
// (where it acts, the app engine's test verdict, a table's findings), a rule
// read as a sentence, and the decision-table model the table editor edits.
// The rule record and the condition editor's mapping are lib/blueprint-rules.
// ---------------------------------------------------------------------------

import { feelToCondition } from "@/lib/feel-to-condition";
import type { ConditionExpression, ConditionGroup, ConditionNode } from "@/types/rules";
import type { Catalogue, RuleView, StoredRule } from "@/lib/blueprint-rules";

export type FiresOn = "create" | "update";

export interface Usage {
  workflow: string;
  name: string;
  step?: string;
  stepName?: string;
  stops?: boolean;
}

export interface Usages {
  steps: Usage[];
  starts: Usage[];
  saves: Usage[];
}

/** A rule as the studio reads it: the view, plus where it acts and when it fires. */
export type StudioView = RuleView & {
  usages?: Usages;
  rule: StoredRule & { on?: FiresOn[]; table?: StudioTableStored };
};

export interface StudioCatalogue extends Catalogue {
  workflows: { id: string; name: string; steps?: { key: string; name: string; type?: string }[] }[];
}

export interface StudioTableStored {
  hitPolicy?: string;
  aggregation?: string;
  inputs?: StoredColumn[];
  outputs?: StoredColumn[];
  rules?: { id?: string; inputEntries: string[]; outputEntries: string[]; annotation?: string }[];
}

export interface StoredColumn {
  id?: string;
  name: string;
  label?: string;
  type?: string;
  variableBinding?: string;
  values?: string[];
}

export interface Finding {
  severity: "error" | "warning";
  kind: "cell" | "overlap" | "unreachable" | "shape" | "value";
  row?: number;
  column?: string;
  message: string;
}

export interface CheckAnswer {
  ok: boolean;
  problems: string[];
  runs?: string;
  statement?: string;
  advice?: string[];
  findings?: Finding[];
}

export interface TraceLine {
  id: string;
  name: string;
  kind: "condition_action" | "decision_table";
  fires: boolean;
  held?: boolean | null;
  error?: string | null;
  matched?: number[];
  used?: number[];
  outputs?: Record<string, unknown>;
  violation?: string | null;
}

export interface TestAnswer {
  ok: boolean;
  problems: string[];
  advice?: string[];
  unavailable?: string;
  event?: FiresOn;
  refused?: boolean;
  errors?: string[];
  patches?: Record<string, unknown>;
  formHints?: { field: string; hidden?: boolean; required?: boolean; readonly?: boolean;
                recommendation?: { value: unknown; message?: string }; options?: unknown[] }[];
  sideEffects?: { type: string; workflow?: string; message?: string }[];
  record?: Record<string, unknown>;
  trace?: TraceLine[];
  focus?: TraceLine | null;
}

// ---- a rule, read as a sentence ---------------------------------------------

const OPERATOR_WORDS: Record<string, string> = {
  equals: "is", not_equals: "is not", gt: "is more than", gte: "is at least", lt: "is less than",
  lte: "is at most", in: "is one of", not_in: "is not one of", is_null: "is blank",
  is_not_null: "is filled in", contains: "contains", starts_with: "starts with", ends_with: "ends with",
  matches_regex: "matches",
};

/** "amount" -> "amount"; "managerNote" -> "manager note". */
export function humanField(name: string): string {
  return String(name).replace(/[_-]+/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
}

function quote(v: unknown): string {
  if (Array.isArray(v)) return v.map(quote).join(", ");
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  const s = String(v ?? "");
  return /^-?\d+(\.\d+)?$/.test(s) ? s : `“${s}”`;
}

function conditionWords(expr: ConditionExpression | null | undefined): string {
  if (!expr) return "always";
  if ("logic" in expr) {
    const g = expr as ConditionGroup;
    const parts = g.conditions.map((c) => {
      const w = conditionWords(c);
      return "logic" in c && (c as ConditionGroup).conditions.length > 1 ? `(${w})` : w;
    });
    if (g.logic === "NOT") return `not (${parts.join(" and ")})`;
    return parts.join(g.logic === "OR" ? " or " : " and ");
  }
  const n = expr as ConditionNode;
  let field = humanField(n.field);
  if (n.field.startsWith("previous.")) field = `the previous ${humanField(n.field.slice(9))}`;
  const op = OPERATOR_WORDS[n.operator] ?? n.operator;
  if (n.operator === "is_null" || n.operator === "is_not_null") return `${field} ${op}`;
  return `${field} ${op} ${quote(n.value)}`;
}

/** The condition in words, or its FEEL text when it is not a simple tree. */
export function whenWords(feel: string | undefined): string {
  const f = (feel || "true").trim();
  if (f === "true" || f === "") return "always";
  const tree = feelToCondition(f);
  return tree ? conditionWords(tree) : `“${f}”`;
}

function actionWords(a: Record<string, any>, cat: StudioCatalogue | null): string {
  const field = a.field ? humanField(a.field) : "";
  switch (a.type) {
    case "show_error": return `refuse it: “${a.message ?? ""}”`;
    case "set_field": return `set ${field} to ${a.valueMode === "formula" ? a.value : quote(a.value)}`;
    case "set_default": return `default ${field} to ${quote(a.value)}`;
    case "clear_field": return `clear ${field}`;
    case "set_required": return a.required === false ? `stop requiring ${field}` : `require ${field}`;
    case "set_visibility": return `${a.visible === false ? "hide" : "show"} ${field}`;
    case "set_readonly": return `${a.readonly === false ? "unlock" : "lock"} ${field}`;
    case "set_options": return `limit ${field} to ${(a.options ?? []).map((o: any) => o.label ?? o.value).join(", ")}`;
    case "recommendation": return `suggest ${quote(a.value)} for ${field}`;
    case "trigger_workflow": {
      const w = cat?.workflows.find((x) => x.id === a.workflow);
      return `start “${w?.name ?? a.workflow}”`;
    }
    case "send_notification": return `notify: “${a.message ?? ""}”`;
    default: return String(a.type ?? "").replace(/_/g, " ");
  }
}

const POLICY_WORDS: Record<string, string> = {
  U: "one row may match", F: "the first matching row wins", P: "the highest-priority value wins",
  A: "matching rows must agree", C: "every matching row counts", R: "every matching row, in order",
};

export function firesWords(on: FiresOn[] | undefined): string {
  if (!on || on.length !== 1) return "is saved";
  return on[0] === "create" ? "is created" : "is updated";
}

/** The whole rule as a sentence a person reads before they read its parts. */
export function ruleSentence(view: StudioView, cat: StudioCatalogue | null): string {
  const r = view.rule;
  const record = view.entityName ? `${/^[aeiou]/i.test(view.entityName) ? "an" : "a"} ${view.entityName}` : "a record";
  if (view.kind === "decision_table") {
    const t = r.table ?? {};
    const ins = (t.inputs ?? []).map((c) => humanField(c.label || c.variableBinding || c.name)).join(", ");
    const outs = (t.outputs ?? []).map((c) => humanField(c.label || c.variableBinding || c.name)).join(", ");
    const n = (t.rules ?? []).length;
    return `When ${record} ${firesWords(r.on)}, set ${outs || "…"} from ${ins || "…"} by a table of ${n} row${n === 1 ? "" : "s"} (${POLICY_WORDS[String(t.hitPolicy || "F").toUpperCase()] ?? "first match"}).`;
  }
  if (view.kind === "condition_action") {
    const cond = whenWords(r.when || r.expression);
    const then = (r.then ?? []).map((a) => actionWords(a as any, cat));
    const otherwise = (r.otherwise ?? []).map((a) => actionWords(a as any, cat));
    let s = `When ${record} ${firesWords(r.on)}`;
    s += cond === "always" ? ", " : ` and ${cond}, `;
    s += then.length ? then.join(", then ") : "nothing";
    if (otherwise.length) s += `; otherwise ${otherwise.join(", then ")}`;
    // A quoted message already ends the sentence: “… a note.” — not “… a note.”.
    return /[.!?]”$/.test(s) ? s : s + ".";
  }
  if (view.kind === "prerequisite") return r.statement || r.name;
  return r.statement || r.name;
}

// ---- the decision-table model ---------------------------------------------

export type HitPolicy = "U" | "F" | "P" | "A" | "C" | "R";
export type Aggregation = "SUM" | "COUNT" | "MIN" | "MAX";

export const HIT_POLICIES: { id: HitPolicy; name: string; says: string; forRecords: boolean }[] = [
  { id: "U", name: "Unique", says: "Exactly one row can match any record. Overlapping rows are caught when you save.", forRecords: true },
  { id: "F", name: "First", says: "Rows are read top to bottom; the first that matches wins.", forRecords: true },
  { id: "P", name: "Priority", says: "Of the rows that match, the one whose result comes first in the result's list of values wins.", forRecords: true },
  { id: "A", name: "Any", says: "Several rows may match, but they must give the same result.", forRecords: true },
  { id: "C", name: "Collect", says: "Every matching row counts: add them up, count them, or take the smallest or largest.", forRecords: true },
  { id: "R", name: "Rule order", says: "Every matching row, as a list in row order — for a workflow step.", forRecords: false },
];

export interface TableColumn {
  key: string;
  field: string;
  label?: string;
  type: string;
  values?: string[];
}

export interface TableRowState {
  key: string;
  inputs: string[];
  outputs: string[];
  note?: string;
}

export interface TableState {
  hitPolicy: HitPolicy;
  aggregation?: Aggregation;
  inputs: TableColumn[];
  outputs: TableColumn[];
  rows: TableRowState[];
}

let seq = 0;
export const newKey = (p: string) => `${p}_${Date.now().toString(36)}_${++seq}`;

export function emptyTable(): TableState {
  return { hitPolicy: "U", inputs: [], outputs: [], rows: [] };
}

export function tableFromStored(t: StudioTableStored | undefined): TableState {
  const col = (c: StoredColumn): TableColumn => ({
    key: newKey("col"), field: c.variableBinding || c.name, label: c.label, type: c.type || "any",
    values: c.values,
  });
  const policy = String(t?.hitPolicy || "F").toUpperCase();
  return {
    hitPolicy: (["U", "F", "P", "A", "C", "R"].includes(policy) ? policy : "F") as HitPolicy,
    aggregation: (["SUM", "COUNT", "MIN", "MAX"].includes(String(t?.aggregation || "").toUpperCase())
      ? String(t?.aggregation).toUpperCase() : undefined) as Aggregation | undefined,
    inputs: (t?.inputs ?? []).map(col),
    outputs: (t?.outputs ?? []).map(col),
    rows: (t?.rules ?? []).map((r) => ({ key: newKey("row"), inputs: [...(r.inputEntries ?? [])],
                                         outputs: [...(r.outputEntries ?? [])], note: r.annotation })),
  };
}

export function tableToStored(t: TableState): StudioTableStored {
  const col = (c: TableColumn): StoredColumn => ({
    name: c.field, variableBinding: c.field, type: c.type,
    ...(c.label ? { label: c.label } : {}), ...(c.values?.length ? { values: c.values } : {}),
  });
  return {
    hitPolicy: t.hitPolicy,
    ...(t.hitPolicy === "C" && t.aggregation ? { aggregation: t.aggregation } : {}),
    inputs: t.inputs.map(col),
    outputs: t.outputs.map(col),
    rules: t.rows.map((r) => ({
      inputEntries: t.inputs.map((_, i) => (r.inputs[i] ?? "").trim() || "-"),
      outputEntries: t.outputs.map((_, i) => (r.outputs[i] ?? "").trim()),
      ...(r.note?.trim() ? { annotation: r.note.trim() } : {}),
    })),
  };
}

/** The column type a field gives a table column. */
export function columnType(fieldType: string): string {
  return fieldType === "enum" ? "string" : ["number", "boolean", "date", "string"].includes(fieldType) ? fieldType : "string";
}

/** The cell syntax, said once where a person types a cell. */
export const CELL_HELP: { example: string; means: string }[] = [
  { example: "-", means: "anything" },
  { example: "travel", means: "exactly this (text needs no quotes)" },
  { example: "travel, meals", means: "either of these" },
  { example: "> 5000", means: "more than (also >=, <, <=, != )" },
  { example: "[1000..5000]", means: "from 1000 to 5000, both included" },
  { example: "(0..100]", means: "above 0, up to and including 100" },
  { example: "not(travel)", means: "anything but this" },
  { example: "> budget", means: "more than another field of the record" },
  { example: '> "2026-06-30"', means: "after a date" },
];

/** Values a sample record field takes from the editor's text box. */
export function coerceSample(value: string, type: string): unknown {
  const v = value.trim();
  if (v === "") return null;
  if (type === "number") return Number.isFinite(Number(v)) ? Number(v) : v;
  if (type === "boolean") return v === "true" ? true : v === "false" ? false : v;
  return v;
}

export function blankRuleOn(on: FiresOn[] | undefined): FiresOn[] {
  return on && on.length ? on : ["create", "update"];
}
