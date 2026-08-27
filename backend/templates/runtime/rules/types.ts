/**
 * Rule type definitions — matches backend/models/rules.py schema.
 */

export type RuleType =
  | "validation"
  | "access"
  | "business"
  | "computed"
  | "state_machine"
  | "trigger"
  | "content_moderation"
  | "similarity_check"
  | "ai_validation"
  | "ai_enrichment"
  // Power-Apps-style Business Rules editor types (authored in the platform,
  // executed here at request time). See ConditionActionConfig / DecisionTableConfig.
  | "condition_action"
  | "decision_table";

export interface ProjectRule {
  id: string;
  name: string;
  rule_type: RuleType;
  model_name?: string | null;
  field_name?: string | null;
  config: Record<string, unknown>;
  is_active: boolean;
}

// ---------------------------------------------------------------------------
// Rule config shapes per type
// ---------------------------------------------------------------------------

export interface ValidationRuleConfig {
  /** FEEL-lite expression that must evaluate to true */
  expression?: string;
  /** Regex pattern (alternative to expression) */
  pattern?: string;
  /** Min length / value */
  min?: number;
  /** Max length / value */
  max?: number;
  /** Required: value must be present */
  required?: boolean;
  /** Error message shown to user */
  errorMessage?: string;
}

export interface AccessRuleConfig {
  /** FEEL-lite expression: user context evaluates to true if allowed */
  condition?: string;
  /** Allowed roles */
  roles?: string[];
  /** Can view */
  can_view?: boolean;
  /** Can edit */
  can_edit?: boolean;
  /** Can delete */
  can_delete?: boolean;
}

export interface BusinessRuleConfig {
  /** FEEL-lite expression that produces the result */
  expression: string;
  /** Trigger: when to evaluate (on_create, on_update, on_read) */
  trigger?: "on_create" | "on_update" | "on_read";
}

export interface ComputedFieldConfig {
  /** FEEL-lite expression that produces the value */
  expression: string;
  /** Cache duration in seconds */
  cacheSeconds?: number;
}

export interface StateMachineConfig {
  /** Allowed states */
  states: string[];
  /** Transition definitions */
  transitions: Array<{
    from: string;
    to: string;
    requires?: string; // role needed
    condition?: string; // FEEL-lite expression
  }>;
  initial?: string;
}

// ---------------------------------------------------------------------------
// Business Rules editor shapes (condition → action) — mirror of
// frontend/src/types/business-rules.ts, evaluated by evaluateRuleSet().
// ---------------------------------------------------------------------------

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

export interface RuleAction {
  id: string;
  type: RuleActionType;
  field?: string;
  valueMode?: "literal" | "field" | "formula";
  value?: string;
  message?: string;
  visible?: boolean;
  required?: boolean;
  readonly?: boolean;
  workflow?: string;
}

export interface ConditionActionConfig {
  source?: string;
  when?: unknown;
  /** Compiled FEEL-lite condition string (authored + compiled in the editor). */
  whenFeel?: string;
  then?: RuleAction[];
  otherwise?: RuleAction[];
  /** entity = form + server; form = client only; server = server only. */
  scope?: "entity" | "form" | "server";
  salience?: number;
}

/** A form-only outcome (visibility/required/readonly/recommendation) — collected
 * server-side but applied on the client; consumed by the renderer. */
export interface FieldHint {
  field: string;
  hidden?: boolean;
  required?: boolean;
  readonly?: boolean;
  recommendation?: { value?: string; message?: string };
}

/** A deferred side effect (fired after a successful write). */
export interface RuleSideEffect {
  type: "trigger_workflow" | "send_notification";
  workflow?: string;
  message?: string;
}

/** The result of evaluating a model's condition→action rule set for one event. */
export interface RuleSetResult {
  /** Field patches to merge into the entity before the write (set/default/clear). */
  patches: Record<string, unknown>;
  /** show_error messages — non-empty means reject the write. */
  errors: string[];
  /** Form-only outcomes (ignored server-side, surfaced to the client). */
  formHints: FieldHint[];
  /** Deferred side effects to fire after the write succeeds. */
  sideEffects: RuleSideEffect[];
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

export interface AccessCheckResult {
  allowed: boolean;
  reason?: string;
}
