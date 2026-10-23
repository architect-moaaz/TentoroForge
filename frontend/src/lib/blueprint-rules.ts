// ---------------------------------------------------------------------------
// Business rules of a Blueprint-built app — what /api/projects/{id}/business-rules
// answers, and the mapping between a stored rule and the tab's editors.
//
// The Blueprint's `businessRules` is the one record of an app's rules: the
// build writes it, Smith writes it, this tab writes it. A rule's condition is
// the FEEL text in `when`; the visual builder's tree is read from it
// (feel-to-condition) and compiled back (condition-to-feel).
// ---------------------------------------------------------------------------

import type { ColumnModel } from "@/types/app-model";
import type { RuleAction, RuleScope } from "@/types/business-rules";
import type { DecisionTableDefinition } from "@/types/decision";
import type { ConditionActionDraft } from "@/components/business-rules/studio/WhenThenEditor";
import { conditionToFeel } from "@/lib/condition-to-feel";
import { feelToCondition, conditionFields } from "@/lib/feel-to-condition";

export type RuleKind = "statement" | "condition_action" | "decision_table" | "prerequisite";
export type RuleOrigin = "brief" | "smith" | "editor" | "generated";
export type RuleRuns = "everywhere" | "form" | "save" | "before" | "nowhere";

/** A rule as stored in the Blueprint (the fields the tab reads). */
export interface StoredRule {
  id: string;
  name: string;
  statement: string;
  kind?: RuleKind;
  entity?: string;
  when?: string;
  expression?: string;
  then?: Omit<RuleAction, "id">[];
  otherwise?: Omit<RuleAction, "id">[];
  scope?: RuleScope;
  salience?: number;
  enabled?: boolean;
  origin?: RuleOrigin;
  table?: {
    hitPolicy?: string;
    inputs?: { id?: string; name: string; label?: string; type?: string; variableBinding?: string }[];
    outputs?: { id?: string; name: string; label?: string; type?: string; variableBinding?: string }[];
    rules?: { id?: string; inputEntries: string[]; outputEntries: string[]; annotation?: string }[];
  };
  gates?: string[];
  message?: string;
  requirements?: string[];
  syncNote?: string;
  status?: string;
}

export interface RuleView {
  rule: StoredRule;
  revision: string;
  kind: RuleKind;
  origin: RuleOrigin;
  enabled: boolean;
  enforced: boolean;
  runs: RuleRuns;
  entityName: string | null;
  gates: { id: string; name: string | null }[];
  requirements: { id: string; description: string | null }[];
}

export interface CatalogueField {
  name: string;
  type: "string" | "number" | "boolean" | "date" | "enum";
  enumValues: string[];
  required: boolean;
}

export interface Catalogue {
  entities: { id: string; name: string; table?: string; fields: CatalogueField[] }[];
  workflows: { id: string; name: string }[];
  requirements: { id: string; description: string }[];
}

export interface RulesResponse {
  mode: "blueprint" | "legacy";
  version: number;
  /** Read-only now: a build, the checks after it, or a Smith turn has the definition open. */
  building: boolean;
  /** Which of them, for the banner. */
  busy?: "building" | "checking" | "smith" | null;
  rules: RuleView[];
  /** Rules the person stated that the build has not written yet. */
  planned?: { id: string; description: string }[];
  catalogue: Catalogue | null;
  /** Workflow checks that repeated a rule, handed to the rule as the list was read. */
  linked?: { rule: string; ruleName?: string; workflow: string; name: string; step: string }[];
}

export const ORIGIN_LABEL: Record<RuleOrigin, string> = {
  brief: "From your request",
  smith: "Added by Smith",
  editor: "Added here",
  generated: "Suggested by Forge",
};

export const RUNS_LABEL: Record<RuleRuns, string> = {
  everywhere: "Checked every time it is saved, and shown on the form",
  form: "Changes how the form looks",
  save: "Checked every time it is saved",
  before: "Checked before its workflows start",
  nowhere: "Not checked",
};

// ---- the data model, in the shape the existing editors take --------------

/** The editors take model NAMES and typed columns; enum columns carry a type
 *  that names their values. */
export function editorModel(cat: Catalogue | null) {
  const entities = cat?.entities ?? [];
  const models = entities.map((e) => e.name);
  const enums = new Map<string, string[]>();
  const columns = new Map<string, ColumnModel[]>();
  for (const e of entities) {
    columns.set(
      e.name,
      e.fields.map((f) => {
        if (f.type === "enum") {
          const t = `enum:${e.name}.${f.name}`;
          enums.set(t, f.enumValues);
          return { name: f.name, type: t, nullable: !f.required };
        }
        const t = f.type === "number" ? "numeric" : f.type === "boolean" ? "boolean"
          : f.type === "date" ? "timestamp" : "text";
        return { name: f.name, type: t, nullable: !f.required };
      }),
    );
  }
  return {
    models,
    hasModel: entities.length > 0,
    getFields: (model: string | null | undefined): ColumnModel[] => (model ? columns.get(model) ?? [] : []),
    enumValuesForType: (type: string | undefined): string[] | null => (type ? enums.get(type) ?? null : null),
    entityIdByName: (name: string | null | undefined) => entities.find((e) => e.name === name)?.id,
    entityNameById: (id: string | null | undefined) => entities.find((e) => e.id === id)?.name ?? null,
  };
}

let actionSeq = 0;
const withIds = (acts: Omit<RuleAction, "id">[] | undefined): RuleAction[] =>
  (acts ?? []).map((a) => ({ ...(a as RuleAction), id: `act_${++actionSeq}` }));
const withoutIds = (acts: RuleAction[]): Omit<RuleAction, "id">[] =>
  acts.map(({ id: _id, ...rest }) => rest);

// ---- condition → action ---------------------------------------------------

export function toConditionDraft(view: RuleView, cat: Catalogue | null): ConditionActionDraft {
  const r = view.rule;
  const feel = (r.when || r.expression || "true").trim() || "true";
  const tree = feelToCondition(feel);
  const fields = new Set(editorModel(cat).getFields(view.entityName).map((c) => c.name));
  // The builder only when the condition is a tree over this record's own fields.
  const builderCan = tree !== undefined && conditionFields(tree).every((f) => fields.has(f));
  return {
    id: r.id,
    name: r.name,
    model_name: view.entityName,
    is_active: view.enabled,
    statement: r.statement,
    expression: !builderCan,
    config: {
      source: "manual",
      when: builderCan ? tree ?? null : null,
      whenFeel: feel,
      then: withIds(r.then),
      otherwise: withIds(r.otherwise),
      scope: r.scope ?? "entity",
      salience: typeof r.salience === "number" ? r.salience : 0,
    },
  };
}

export function conditionPayload(draft: ConditionActionDraft, entityId: string | undefined) {
  const when = draft.expression ? draft.config.whenFeel : conditionToFeel(draft.config.when) || "true";
  return {
    kind: "condition_action" as const,
    name: draft.name.trim(),
    statement: (draft.statement ?? "").trim(),
    entity: entityId,
    when: when.trim() || "true",
    then: withoutIds(draft.config.then),
    otherwise: withoutIds(draft.config.otherwise),
    scope: draft.config.scope,
    salience: draft.config.salience,
    enabled: draft.is_active,
  };
}

// ---- decision tables -------------------------------------------------------

export interface TableDraft {
  id?: string;
  name: string;
  statement?: string;
  is_active: boolean;
  model: string | null;
  table: DecisionTableDefinition;
}

let tableSeq = 0;
export function toTableDraft(view: RuleView): TableDraft {
  const t = view.rule.table ?? {};
  const n = ++tableSeq;
  return {
    id: view.rule.id,
    name: view.rule.name,
    statement: view.rule.statement,
    is_active: view.enabled,
    model: view.entityName,
    table: {
      id: `dt_${n}`,
      name: view.rule.name,
      hitPolicy: (t.hitPolicy as DecisionTableDefinition["hitPolicy"]) ?? "F",
      inputs: (t.inputs ?? []).map((c, i) => ({ id: c.id ?? `in_${n}_${i}`, name: c.name, label: c.label,
        type: (c.type as DecisionTableDefinition["inputs"][number]["type"]) ?? "any",
        variableBinding: c.variableBinding ?? c.name })),
      outputs: (t.outputs ?? []).map((c, i) => ({ id: c.id ?? `out_${n}_${i}`, name: c.name, label: c.label,
        type: (c.type as DecisionTableDefinition["outputs"][number]["type"]) ?? "any" })),
      rules: (t.rules ?? []).map((r, i) => ({ id: r.id ?? `r_${n}_${i}`, inputEntries: r.inputEntries,
        outputEntries: r.outputEntries, annotation: r.annotation })),
    },
  };
}

export function tablePayload(draft: TableDraft, entityId: string | undefined) {
  const t = draft.table;
  return {
    kind: "decision_table" as const,
    name: draft.name.trim(),
    statement: (draft.statement ?? "").trim(),
    entity: entityId,
    enabled: draft.is_active,
    table: {
      hitPolicy: t.hitPolicy,
      inputs: t.inputs.map((c) => ({ name: c.variableBinding || c.name, label: c.label, type: c.type,
        variableBinding: c.variableBinding || c.name })),
      outputs: t.outputs.map((c) => ({ name: c.name, label: c.label, type: c.type })),
      rules: t.rules.map((r) => ({ inputEntries: r.inputEntries, outputEntries: r.outputEntries,
        ...(r.annotation ? { annotation: r.annotation } : {}) })),
    },
  };
}

// ---- written-down rules ----------------------------------------------------

export interface StatementDraft {
  id?: string;
  name: string;
  statement: string;
  is_active: boolean;
}

export const statementPayload = (d: StatementDraft) => ({
  kind: "statement" as const, name: d.name.trim(), statement: d.statement.trim(), enabled: d.is_active,
});

/** The server's refusal, in the person's words: `{message, problems}` or text. */
export function problemsOf(err: unknown): string[] {
  const e = err as { detail?: unknown; message?: string; body?: { detail?: unknown } };
  const detail = (e?.body?.detail ?? e?.detail) as { message?: string; problems?: string[] } | string | undefined;
  if (detail && typeof detail === "object" && Array.isArray(detail.problems) && detail.problems.length) {
    return detail.problems;
  }
  if (detail && typeof detail === "object" && detail.message) return [detail.message];
  if (typeof detail === "string") return [detail];
  return [e?.message || "The rule could not be saved."];
}
