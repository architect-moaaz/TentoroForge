// ---------------------------------------------------------------------------
// Business Rules editor types
//
// A business rule is a Power-Apps-style "WHEN <condition> THEN <action(s)>
// [ELSE <action(s)>]" declaration, persisted as a ProjectRule row
// (rule_type="condition_action") via the existing /api/projects/{id}/rules
// CRUD. The visual condition tree (ConditionExpression from @/types/rules) is
// reused for the IF side; the action vocabulary below is the THEN/ELSE side.
//
// config.source is always "manual" so the rules_agent regeneration wipe
// preserves editor-authored rules (see backend agents/rules_agent.py).
// ---------------------------------------------------------------------------

import type { ConditionExpression } from "@/types/rules";

/** Power-Apps action vocabulary (+ our workflow/notification extensions). */
export type RuleActionType =
  | "set_field"
  | "set_default"
  | "clear_field"
  | "show_error"
  | "set_visibility"
  | "set_required"
  | "set_readonly"
  | "set_options"
  | "recommendation"
  | "trigger_workflow"
  | "send_notification";

export type ValueMode = "literal" | "field" | "formula";

export interface RuleAction {
  id: string;
  type: RuleActionType;
  /** Target field for set/clear/visibility/required/readonly/recommendation. */
  field?: string;
  /** How `value` is interpreted (set_field / set_default). */
  valueMode?: ValueMode;
  /** Literal value, source field name, or FEEL formula (per valueMode). */
  value?: string;
  /** Error / recommendation message (show_error, recommendation, notification). */
  message?: string;
  /** set_visibility */
  visible?: boolean;
  /** set_required */
  required?: boolean;
  /** set_readonly (lock/unlock) */
  readonly?: boolean;
  /** trigger_workflow — the workflow's id (FLOW-…) on a Blueprint app. */
  workflow?: string;
  /** set_options — the options the field offers while the rule holds. */
  options?: { value: string; label: string }[];
}

export type RuleScope = "entity" | "form" | "server";

/** config shape for a rule_type="condition_action" ProjectRule. */
export interface ConditionActionConfig {
  source: "manual";
  /** Visual condition tree — round-trippable in the editor. */
  when: ConditionExpression | null;
  /** Compiled FEEL-lite string — what the runtime / playground evaluates. */
  whenFeel: string;
  /** Actions to run when the condition is TRUE (the ✓ branch). */
  then: RuleAction[];
  /** Actions to run when the condition is FALSE (the ✗ branch). */
  otherwise: RuleAction[];
  scope: RuleScope;
  /** Higher salience fires first (Drools-style conflict resolution). */
  salience: number;
}

/** config shape for a rule_type="decision_table" ProjectRule. */
export interface DecisionTableConfig {
  source: "manual";
  // DecisionTableDefinition from @/types/decision (kept loose to avoid a hard
  // dependency cycle; the editor casts it where needed).
  table: Record<string, unknown>;
}

export type BusinessRuleType = "condition_action" | "decision_table";

/** A persisted ProjectRule as the business-rules editor consumes it. */
export interface BusinessRule {
  id: string;
  project_id: string;
  name: string;
  rule_type: BusinessRuleType;
  model_name: string | null;
  field_name: string | null;
  config: ConditionActionConfig | DecisionTableConfig | Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** UI metadata per action type — labels + which inputs the action needs. */
export const ACTION_META: Record<
  RuleActionType,
  {
    label: string;
    description: string;
    /** Form-only actions are ignored server-side (Power-Apps semantics). */
    formOnly: boolean;
    needsField: boolean;
    needsValue: boolean;
    needsMessage: boolean;
  }
> = {
  set_field: {
    label: "Fill in a value",
    description: "Put a value in a field: a fixed value, another field, or a calculation.",
    formOnly: false,
    needsField: true,
    needsValue: true,
    needsMessage: false,
  },
  set_default: {
    label: "Fill in if left empty",
    description: "Put a value in a field, but only if it was left empty.",
    formOnly: false,
    needsField: true,
    needsValue: true,
    needsMessage: false,
  },
  clear_field: {
    label: "Empty a field",
    description: "Remove what is in a field.",
    formOnly: false,
    needsField: true,
    needsValue: false,
    needsMessage: false,
  },
  show_error: {
    label: "Stop and show a message",
    description: "Don't save it, and show this message to the person.",
    formOnly: false,
    needsField: false,
    needsValue: false,
    needsMessage: true,
  },
  set_visibility: {
    label: "Show or hide a field",
    description: "Show or hide a field on the form.",
    formOnly: true,
    needsField: true,
    needsValue: false,
    needsMessage: false,
  },
  set_required: {
    label: "Make a field required",
    description: "The field must be filled in. If it is empty, it won't be saved.",
    formOnly: false,
    needsField: true,
    needsValue: false,
    needsMessage: false,
  },
  set_readonly: {
    label: "Lock or unlock a field",
    description: "Stop people changing a field, or let them change it again.",
    formOnly: true,
    needsField: true,
    needsValue: false,
    needsMessage: false,
  },
  set_options: {
    label: "Limit the choices",
    description: "Only offer these choices in a field.",
    formOnly: true,
    needsField: true,
    needsValue: false,
    needsMessage: false,
  },
  recommendation: {
    label: "Suggest a value",
    description: "Show a suggestion the person can accept with one click.",
    formOnly: true,
    needsField: true,
    needsValue: true,
    needsMessage: true,
  },
  trigger_workflow: {
    label: "Start a workflow",
    description: "Start one of the app's workflows for this item.",
    formOnly: false,
    needsField: false,
    needsValue: false,
    needsMessage: false,
  },
  send_notification: {
    label: "Send a notification",
    description: "Send a message inside the app.",
    formOnly: false,
    needsField: false,
    needsValue: false,
    needsMessage: true,
  },
};

export const ACTION_TYPES: RuleActionType[] = [
  "set_field",
  "set_default",
  "clear_field",
  "show_error",
  "set_visibility",
  "set_required",
  "set_readonly",
  "set_options",
  "recommendation",
  "trigger_workflow",
  "send_notification",
];
