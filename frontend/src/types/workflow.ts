// ---------------------------------------------------------------------------
// Node Types
// ---------------------------------------------------------------------------

export type WorkflowNodeType =
  | "trigger"
  | "action"
  | "condition"
  | "decision"
  | "wait"
  | "end"
  | "end_event"
  | "assignment"
  | "approval"
  | "task_pool"
  | "escalation"
  | "user_task"
  | "exclusive_gateway"
  | "parallel_gateway"
  | "fork"
  | "join"
  | "ai_classify"
  | "ai_extract"
  | "ai_decide"
  | "ai_generate";

export interface NodeCategoryItem {
  id: string;
  type: WorkflowNodeType;
  label: string;
  icon: string;
  description: string;
  gradient: string;
  defaultConfig?: Partial<WorkflowNodeConfig>;
}

export interface NodeCategory {
  label: string;
  nodes: NodeCategoryItem[];
}

// The palette is derived from the workflow node catalog
// (src/catalog/workflow-nodes.json) — the same list the workflow agent authors
// against and the engine executes. Re-exported here so existing imports hold.
export { NODE_CATEGORIES } from "@/catalog/workflowNodes";

// ---------------------------------------------------------------------------
// Trigger Config
// ---------------------------------------------------------------------------

export type TriggerType = "api_event" | "schedule" | "db_change" | "webhook" | "manual";

export interface TriggerConfig {
  type: TriggerType;
  event?: string;         // api_event
  cron?: string;          // schedule
  model?: string;         // db_change
  field?: string;         // db_change
  condition?: string;     // db_change
  path?: string;          // webhook
  name?: string;          // manual
}

// ---------------------------------------------------------------------------
// Step / Node Config
// ---------------------------------------------------------------------------

export type ActionType =
  | "db_query"
  | "db_insert"
  | "db_update"
  | "db_delete"
  | "http_call"
  | "send_email"
  | "send_notification"
  | "set_variable"
  | "transform"
  | "generate_document"
  | "mcp_tool_call"
  | "emit_event"
  | "wait_for_event"
  | "custom" | "ocr_document";

export type ApprovalType = "single" | "sequential" | "parallel_all" | "parallel_any" | "threshold";

export type AssignType =
  | "role"
  | "group"
  | "department"
  | "person"
  | "team"
  | "manager_of_requester"
  | "department_head"
  | "initiator"
  | "process_variable";

export interface WorkflowNodeConfig {
  // General
  nodeType?: string;

  // Trigger node (stored in config alongside other trigger fields)
  type?: TriggerType;

  // Action node
  actionType?: ActionType;
  description?: string;

  // Condition node
  expression?: string;
  conditionMode?: "visual" | "expression";
  conditionTree?: import("@/types/rules").ConditionExpression | null;

  // Decision node
  decisionTableId?: string;
  decisionTable?: import("@/types/decision").DecisionTableDefinition;
  outputMapping?: Record<string, string>;

  // Wait node
  duration?: string;
  durationMs?: number;

  // Assignment / Approval node
  assignType?: AssignType;
  assignTarget?: string;
  assignTargetName?: string;
  assignVariablePath?: string;
  approvalType?: ApprovalType;
  requiredApprovals?: number;  // for threshold
  slaHours?: number;

  // Escalation node
  escalateTo?: string;
  escalateToName?: string;
  escalateAssignType?: "role" | "person" | "group" | "department" | "team";

  // DB Query action
  query?: string;
  model?: string;

  // DB Insert/Update/Delete action
  table?: string;

  // Set Variable action
  variableName?: string;

  // HTTP Call action
  url?: string;
  method?: string;
  headers?: Record<string, string>;
  body?: string;

  // Email action
  to?: string;
  subject?: string;
  template?: string;

  // AI Classify node
  aiInput?: string;
  aiLabels?: string[];
  aiPrompt?: string;
  aiConfidenceThreshold?: number;

  // AI Extract node
  aiExtractFields?: { name: string; type: string }[];
  /** Reference to an uploaded file id ({{input.fileId}}); read natively as a PDF/image. */
  aiFileRef?: string;

  // AI (any node) — model override; defaults to the app's FORGE_AI_MODEL.
  aiModel?: string;

  // AI Decide node
  aiContext?: string;
  aiOptions?: string[];
  aiRules?: string[];

  // AI Generate node
  aiTone?: string;
  aiMaxLength?: number;
  aiMaxTokens?: number;

  // Linked Page (for assignment, approval, task_pool nodes)
  pageId?: string;
  pageName?: string;

  // --- New: Process variable I/O per node ---
  inputParams?: NodeParam[];
  outputParams?: NodeParam[];

  // --- New: Form binding for approval/user_task ---
  formBinding?: FormBinding;

  // --- New: Assignment strategy for approval/user_task ---
  assignment?: AssignmentConfig;

  // --- New: Trigger input mapping ---
  inputMapping?: Record<string, string>;

  // --- Contract-shape node I/O (v2) ---
  // Every input row the user has authored via the Properties panel.
  // The runtime input assembler reads these first; if absent (legacy
  // nodes), it falls back to the flat config fields above.
  inputMappings?: {
    name: string;
    source: "variable" | "literal" | "expression";
    value: unknown;
  }[];
  // Opt-in promotion of declared outputs to named process variables.
  // Blank / missing entries do NOT block downstream access — every
  // declared output is always reachable as `<nodeId>.output.<field>`.
  outputMappings?: {
    output: string;
    processVar: string;
  }[];
}

// ---------------------------------------------------------------------------
// Workflow Node Data (for React Flow)
// ---------------------------------------------------------------------------

export interface WorkflowNodeData extends Record<string, unknown> {
  label: string;
  nodeType: WorkflowNodeType;
  config: WorkflowNodeConfig;
  status?: "idle" | "running" | "completed" | "failed";
}

// ---------------------------------------------------------------------------
// Workflow Edge Types
// ---------------------------------------------------------------------------

export type WorkflowEdgeType = "default" | "then" | "else" | "error";

export interface WorkflowEdgeData extends Record<string, unknown> {
  edgeType: WorkflowEdgeType;
  label?: string;
}

// ---------------------------------------------------------------------------
// Step Definition (serialized format)
// ---------------------------------------------------------------------------

export interface StepDefinition {
  id: string;
  type: WorkflowNodeType;
  actionFile?: string;
  condition?: string;
  thenStep?: string;
  elseStep?: string;
  nextStep?: string;
  onErrorStep?: string;
  config: WorkflowNodeConfig;
}

// ---------------------------------------------------------------------------
// Workflow Definition
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Process Variables & Node I/O (workflow data context)
// ---------------------------------------------------------------------------

export interface ProcessVariable {
  name: string;
  type: "string" | "number" | "boolean" | "object" | "array" | "date";
  defaultValue?: unknown;
  description?: string;
  required?: boolean;
}

export interface NodeParam {
  name: string;
  type: "string" | "number" | "boolean" | "object" | "array" | "date";
  source?: string;  // reads from this process variable
  target?: string;  // writes to this process variable
  label?: string;
  required?: boolean;
  defaultValue?: unknown;
}

// ---------------------------------------------------------------------------
// Form Binding (for approval/user_task nodes)
// ---------------------------------------------------------------------------

export interface FormField {
  name: string;
  label: string;
  inputType: "text" | "number" | "select" | "textarea" | "date" | "checkbox" | "radio" | "email" | "file";
  options?: Array<{ label: string; value: string }>;
  placeholder?: string;
  required?: boolean;
  pattern?: string;
  source?: string;    // pre-fill from process variable
  target?: string;    // write to process variable on submit
  readOnly?: boolean;
}

export interface FormBinding {
  title: string;
  description?: string;
  fields: FormField[];
  submitLabel?: string;
  rejectLabel?: string;
  component?: string;  // reference to palette component
}

// ---------------------------------------------------------------------------
// Assignment Strategy
// ---------------------------------------------------------------------------

export type AssignmentStrategy =
  | "role"
  | "entity_field"
  | "reporting_manager"
  | "department_head"
  | "round_robin"
  | "creator"
  | "group";

export interface AssignmentConfig {
  strategy: AssignmentStrategy;
  value?: string;       // role name, field name, group name (depends on strategy)
  description?: string;
  fallback?: string;    // fallback assignment (e.g., "role:Admin")
}

export interface WorkflowDefinition {
  id: string;
  name: string;
  description?: string;
  processVariables?: ProcessVariable[];
  definition: {
    trigger: TriggerConfig & {
      inputMapping?: Record<string, string>;  // payload field → process variable
    };
    steps: StepDefinition[];
    nodes: WorkflowNodeSerialized[];
    edges: WorkflowEdgeSerialized[];
  };
}

export interface WorkflowNodeSerialized {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: WorkflowNodeData;
}

export interface WorkflowEdgeSerialized {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
  data?: WorkflowEdgeData;
}

// ---------------------------------------------------------------------------
// Workflow List Item (from API)
// ---------------------------------------------------------------------------

export interface WorkflowListItem {
  id: string;
  name: string;
  description: string | null;
  trigger_type: string | null;
  step_count: number;
}

// ---------------------------------------------------------------------------
// Execution Log
// ---------------------------------------------------------------------------

export interface StepLog {
  stepId: string;
  startedAt: string;
  completedAt?: string;
  status: "running" | "completed" | "failed" | "skipped";
  result?: Record<string, unknown>;
  error?: string;
  durationMs?: number;
}

export interface ExecutionLog {
  workflowId: string;
  startedAt: string;
  completedAt?: string;
  status: "running" | "completed" | "failed";
  steps: StepLog[];
  triggerData?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Assignment Policy
// ---------------------------------------------------------------------------

export interface WorkflowAssignmentPolicy {
  id: string;
  project_id: string;
  workflow_id: string;
  node_id: string;
  assign_type: AssignType;
  assign_target: string | null;
  sla_hours: number | null;
  escalate_to: string | null;
  created_at: string;
}
