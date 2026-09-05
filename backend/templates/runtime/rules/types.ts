/**
 * Rule type definitions — matches backend/models/rules.py schema.
 */

export type RuleType =
  | "validation"
  | "access"
  // Row-level read access: which ROWS of a model an actor may reach, as
  // opposed to `access`, which decides which COLUMNS come back. Compiled to a
  // WHERE clause by rules/row-access-sql.ts rather than evaluated per row.
  | "row_access"
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

export interface RowAccessRuleConfig {
  /** Visual condition tree — round-trippable in the editor. */
  when?: unknown;
  /**
   * Compiled FEEL-lite — what the data engine turns into SQL. Named to match
   * ConditionActionConfig, which already pairs a tree with its compiled text;
   * a second convention for the same idea is a second thing to remember.
   *
   * Evaluated over the row's own columns plus `user.<field>`. TRUE = readable.
   */
  whenFeel: string;
  /**
   * Roles this rule grants to. Empty or absent = every role.
   *
   * Rules on a model are GRANTS that union: an actor reaches a row if ANY rule
   * addressed to them says so. An actor addressed by NO rule on a model that
   * has rules reaches nothing — the same fail-closed reading `canAccessField`
   * uses, so a role is never granted rows by having been forgotten.
   */
  roles?: string[];
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
  | "set_options"
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
  /** set_options: what the field offers while the condition holds. */
  options?: Array<{ value: string; label: string }>;
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
  recommendation?: { value?: string; message?: string
  /** set_options — the options the field offers while a rule holds. */
  options?: Array<{ value: string; label: string }>;
};
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
