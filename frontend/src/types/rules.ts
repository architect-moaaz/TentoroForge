// ---------------------------------------------------------------------------
// Rule Types
// ---------------------------------------------------------------------------

export type RuleType =
  | "validation"
  | "access"
  // Which ROWS an actor may reach, as opposed to `access`, which decides which
  // COLUMNS come back. Compiled into the query's WHERE clause by the data
  // engine, so a hidden row is absent from counts and aggregates too.
  | "row_access"
  | "business"
  | "computed"
  | "state_machine"
  | "trigger"
  | "content_moderation"
  | "similarity_check"
  | "ai_validation"
  | "ai_enrichment";

export const RULE_TYPES: { value: RuleType; label: string }[] = [
  { value: "validation", label: "Validation" },
  { value: "access", label: "Access Control" },
  { value: "row_access", label: "Row Access" },
  { value: "business", label: "Business Rule" },
  { value: "computed", label: "Computed Field" },
  { value: "state_machine", label: "State Machine" },
  { value: "trigger", label: "Trigger" },
  { value: "content_moderation", label: "Content Moderation" },
  { value: "similarity_check", label: "Similarity Check" },
  { value: "ai_validation", label: "AI Validation" },
  { value: "ai_enrichment", label: "AI Enrichment" },
];

// ---------------------------------------------------------------------------
// Condition Builder Types
// ---------------------------------------------------------------------------

export type ConditionOperator =
  | "equals"
  | "not_equals"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "in"
  | "not_in"
  | "is_null"
  | "is_not_null"
  | "matches_regex"
  | "contains"
  | "starts_with"
  | "ends_with";

export const CONDITION_OPERATORS: { value: ConditionOperator; label: string }[] = [
  { value: "equals", label: "equals" },
  { value: "not_equals", label: "not equals" },
  { value: "gt", label: ">" },
  { value: "gte", label: ">=" },
  { value: "lt", label: "<" },
  { value: "lte", label: "<=" },
  { value: "in", label: "in" },
  { value: "not_in", label: "not in" },
  { value: "is_null", label: "is null" },
  { value: "is_not_null", label: "is not null" },
  { value: "matches_regex", label: "matches regex" },
  { value: "contains", label: "contains" },
  { value: "starts_with", label: "starts with" },
  { value: "ends_with", label: "ends with" },
];

export interface ConditionNode {
  id: string;
  field: string;
  operator: ConditionOperator;
  value: string;
}

export interface ConditionGroup {
  id: string;
  logic: "AND" | "OR" | "NOT";
  conditions: (ConditionNode | ConditionGroup)[];
}

export type ConditionExpression = ConditionNode | ConditionGroup;

// ---------------------------------------------------------------------------
// Rule Definition
// ---------------------------------------------------------------------------

export interface Rule {
  id: string;
  project_id: string;
  name: string;
  rule_type: RuleType;
  model_name: string | null;
  field_name: string | null;
  config: RuleConfig;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface RuleConfig {
  // Validation
  condition?: ConditionExpression;
  errorMessage?: string;
  enforcement?: ("api" | "ui" | "db")[];

  // Access Control
  actions?: Record<string, Record<string, "allow" | "deny">>;

  // Row Access — `when` is the visual tree, `whenFeel` the compiled FEEL-lite
  // the data engine turns into a WHERE clause. `roles` names who the rule
  // grants to; rules on a model union, and an actor no rule addresses reaches
  // no rows.
  when?: ConditionExpression | null;
  whenFeel?: string;
  roles?: string[];

  // Business Rule
  triggerAction?: string;
  consequence?: string;

  // Computed Field
  targetField?: string;
  expression?: string;

  // State Machine
  stateField?: string;
  states?: string[];
  transitions?: StateTransition[];

  // Trigger
  watchField?: string;
  actionDescription?: string;

  // Content Moderation (AI)
  policy?: string;
  moderationAction?: "flag" | "reject" | "redact";

  // Similarity Check (AI)
  similarityFields?: string[];
  similarityThreshold?: number;
  similarityAction?: "warn" | "block" | "merge_suggest";

  // AI Validation
  aiValidationPrompt?: string;
  aiValidationFields?: string[];
  aiValidationAction?: "flag" | "reject";

  // AI Enrichment
  aiEnrichTriggerField?: string;
  aiEnrichFields?: string[];
  aiEnrichPrompt?: string;
}

export interface StateTransition {
  from: string;
  to: string;
  condition?: string;
  label?: string;
}

// ---------------------------------------------------------------------------
// Access Policy Types
// ---------------------------------------------------------------------------

export interface AccessPolicy {
  id: string;
  project_id: string;
  target_type: "role" | "group" | "department" | "person";
  target_id: string;
  access_level: "user" | "admin" | "none";
  created_at: string;
}

export interface FieldAccessPolicy {
  id: string;
  project_id: string;
  model_name: string;
  field_name: string;
  target_type: "role" | "group" | "department" | "person";
  target_id: string;
  can_view: boolean;
  can_edit: boolean;
  condition: string | null;
  created_at: string;
}

export interface FieldAccessMatrixCell {
  field_name: string;
  target_id: string;
  target_type: string;
  can_view: boolean;
  can_edit: boolean;
}

export interface FieldAccessMatrixTarget {
  id: string;
  type: string;
  name: string;
}

export interface FieldAccessMatrix {
  model_name: string;
  fields: string[];
  targets: FieldAccessMatrixTarget[];
  cells: FieldAccessMatrixCell[];
}
