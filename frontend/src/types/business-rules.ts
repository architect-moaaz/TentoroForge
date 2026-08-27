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
  /** trigger_workflow */
  workflow?: string;
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
    label: "Set field value",
    description: "Set a field to a value, another field, or a formula.",
    formOnly: false,
    needsField: true,
    needsValue: true,
    needsMessage: false,
  },
  set_default: {
    label: "Set default value",
    description: "Set the field only when it is currently empty.",
    formOnly: false,
    needsField: true,
    needsValue: true,
    needsMessage: false,
  },
  clear_field: {
    label: "Clear field",
    description: "Clear a field's value.",
    formOnly: false,
    needsField: true,
    needsValue: false,
    needsMessage: false,
  },
  show_error: {
    label: "Show error (reject)",
    description: "Block the save and show a validation message.",
    formOnly: false,
    needsField: false,
    needsValue: false,
    needsMessage: true,
  },
  set_visibility: {
    label: "Show / hide field",
    description: "Toggle a field's visibility on the form.",
    formOnly: true,
    needsField: true,
    needsValue: false,
    needsMessage: false,
  },
  set_required: {
    label: "Set required",
    description: "Make a field business-required or optional.",
    formOnly: true,
    needsField: true,
    needsValue: false,
    needsMessage: false,
  },
  set_readonly: {
    label: "Lock / unlock field",
    description: "Make a field read-only or editable.",
    formOnly: true,
    needsField: true,
    needsValue: false,
    needsMessage: false,
  },
  recommendation: {
    label: "Recommendation",
    description: "Suggest a change the user can accept (lightbulb).",
    formOnly: true,
    needsField: true,
    needsValue: true,
    needsMessage: true,
  },
  trigger_workflow: {
    label: "Trigger workflow",
    description: "Fire a workflow by name.",
    formOnly: false,
    needsField: false,
    needsValue: false,
    needsMessage: false,
  },
  send_notification: {
    label: "Send notification",
    description: "Send an in-app notification.",
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
  "recommendation",
  "trigger_workflow",
  "send_notification",
];
