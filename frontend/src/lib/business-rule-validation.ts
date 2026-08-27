// Pre-save validation for business rules authored in the Business Rules editor.
//
// Before this, `canSave` only checked the rule name — so a rule with an action
// missing its target field/value/message, or a rule whose THEN branch was empty
// (a rule that does nothing), saved silently and then no-op'd at runtime. This is
// the authoring feature's guard rail: it returns a list of human-readable problems;
// an empty list means the rule is safe to persist.

import { ACTION_META, type RuleAction } from "@/types/business-rules";
import type { ConditionActionConfig } from "@/types/business-rules";

/** Validate a single THEN/ELSE action's required parameters. */
export function validateAction(action: RuleAction, branch: "then" | "else"): string[] {
  const meta = ACTION_META[action.type];
  const errs: string[] = [];
  const where = `${branch === "then" ? "Then" : "Else"} → ${meta?.label ?? action.type}`;
  if (!meta) return [`${where}: unknown action type "${action.type}"`];

  if (meta.needsField && !(action.field ?? "").trim()) {
    errs.push(`${where}: choose a target field.`);
  }
  if (meta.needsValue && !(action.value ?? "").trim()) {
    errs.push(`${where}: enter a value.`);
  }
  if (meta.needsMessage && !(action.message ?? "").trim()) {
    errs.push(`${where}: enter a message.`);
  }
  if (action.type === "trigger_workflow" && !(action.workflow ?? "").trim()) {
    errs.push(`${where}: choose a workflow to trigger.`);
  }
  return errs;
}

/** Validate a condition→action rule draft. Returns [] when the rule is savable. */
export function validateConditionActionRule(
  name: string,
  modelName: string | null | undefined,
  config: Pick<ConditionActionConfig, "then" | "otherwise">,
): string[] {
  const errs: string[] = [];
  if (!name.trim()) errs.push("Give the rule a name.");
  if (!(modelName ?? "").trim()) errs.push("Choose the model this rule applies to.");

  const then = config.then ?? [];
  const otherwise = config.otherwise ?? [];
  if (then.length === 0 && otherwise.length === 0) {
    errs.push("Add at least one action — a rule with no actions does nothing.");
  }
  for (const a of then) errs.push(...validateAction(a, "then"));
  for (const a of otherwise) errs.push(...validateAction(a, "else"));
  return errs;
}

/** Validate a decision-table rule draft. Returns [] when savable.
 * The table is typed loosely (DecisionTableConfig.table is Record<string,unknown>
 * to avoid a dependency cycle) so we read its columns defensively. */
export function validateDecisionTableRule(
  name: string,
  table: unknown,
): string[] {
  const errs: string[] = [];
  if (!name.trim()) errs.push("Give the decision table a name.");
  const t = (table ?? {}) as {
    inputs?: unknown[];
    outputs?: unknown[];
    rules?: unknown[];
  };
  if (!Array.isArray(t.inputs) || t.inputs.length === 0)
    errs.push("Add at least one input column.");
  if (!Array.isArray(t.outputs) || t.outputs.length === 0)
    errs.push("Add at least one output column.");
  if (!Array.isArray(t.rules) || t.rules.length === 0)
    errs.push("Add at least one rule row.");
  return errs;
}
