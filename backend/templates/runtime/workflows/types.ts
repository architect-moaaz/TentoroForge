/**
 * Workflow type definitions.
 *
 * Every workflow is a directed graph of nodes connected by edges.
 * Data flows through the graph via process variables:
 *   - Each node declares inputParams (what it reads) and outputParams (what it writes)
 *   - The engine resolves inputParams from process variables before executing
 *   - After execution, outputParams are written back to process variables
 *   - Conditions and expressions reference process variables by name
 *
 * Node types:
 *   trigger      — entry point, fires on event/schedule/manual
 *   action       — automated step (db_query, http_call, send_email, custom)
 *   condition    — evaluates expression, routes to then/else edges
 *   approval     — pauses for human decision (approve/reject)
 *   user_task    — pauses for human input (form submission)
 *   wait         — delays execution for a duration
 *   fork/join    — parallel execution
 *   end          — terminal node
 */

// ── Enums ──────────────────────────────────────────────────────────

export type TriggerType =
  | "manual"
  | "api_event"
  | "schedule"
  | "webhook"
  | "db_change"
  | "user_input"
  | "timer";

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
  | "custom"
  | "generate_document"
  | "emit_event"
  | "wait_for_event"
  | "ai_generate"
  | "ai_classify"
  | "ai_extract"
  | "ai_decide"
  | "mcp_tool_call"
  | "ocr_document";

export type NodeType =
  | "trigger"
  | "action"
  | "condition"
  | "decision"
  | "parallel_gateway"
  | "exclusive_gateway"
  | "fork"
  | "join"
  | "user_task"
  | "approval"
  | "assignment"
  | "task_pool"
  | "escalation"
  | "wait"
  | "end"
  | "end_event"
  | "ai_generate"
  | "ai_classify"
  | "ai_extract"
  | "ai_decide";

// ── Process Variable ───────────────────────────────────────────────

export interface ProcessVariable {
  /** Variable name — referenced in expressions and I/O mappings */
  name: string;
  /** Data type */
  type: "string" | "number" | "boolean" | "object" | "array" | "date";
  /** Default value (used if not set by any node) */
  defaultValue?: unknown;
  /** Human-readable description */
  description?: string;
  /** Whether this is required for the workflow to start */
  required?: boolean;
}

// ── Node I/O Parameters ────────────────────────────────────────────

export interface NodeParam {
  /** Parameter name (local to the node) */
  name: string;
  /** Data type */
  type: "string" | "number" | "boolean" | "object" | "array" | "date";
  /** Maps to a process variable (e.g., "patientId" → reads from process var "patientId") */
  source?: string;
  /** For output: the process variable to write to */
  target?: string;
  /** Human label for form fields */
  label?: string;
  /** Whether this input is required */
  required?: boolean;
  /** Default value */
  defaultValue?: unknown;
}

// ── Form Binding (for user_task / approval nodes) ──────────────────

export interface FormField {
  /** Field name — maps to a process variable */
  name: string;
  /** Display label */
  label: string;
  /** Input type: text, number, select, textarea, date, checkbox, radio */
  inputType: "text" | "number" | "select" | "textarea" | "date" | "checkbox" | "radio" | "email" | "file";
  /** For select/radio: available options */
  options?: Array<{ label: string; value: string }>;
  /** Placeholder text */
  placeholder?: string;
  /** Validation: required */
  required?: boolean;
  /** Validation: regex pattern */
  pattern?: string;
  /** Read from process variable (pre-fill) */
  source?: string;
  /** Write to process variable on submit */
  target?: string;
}

export interface FormBinding {
  /** Form title */
  title: string;
  /** Form description */
  description?: string;
  /** Fields to render */
  fields: FormField[];
  /** Submit button label */
  submitLabel?: string;
  /** For approval: reject button label */
  rejectLabel?: string;
  /** Component reference from the palette (e.g., "PatientForm", "Card") */
  component?: string;
}

// ── Node Config ────────────────────────────────────────────────────

export interface NodeConfig {
  // ── Trigger
  type?: TriggerType;
  event?: string;
  schedule?: string;

  // ── Condition / Decision
  /** FEEL-lite expression evaluated against process variables */
  expression?: string;

  // ── Action
  actionType?: ActionType;

  // db_query / db_insert / db_update / db_delete
  table?: string;
  query?: string;
  where?: Record<string, string>;  // field → process variable
  values?: Record<string, string>; // field → process variable

  // http_call
  url?: string;
  method?: string;
  headers?: Record<string, string>;
  body?: unknown;

  // send_email
  to?: string;       // process variable or literal
  subject?: string;
  template?: string;

  // send_notification
  message?: string;
  channel?: string;

  // set_variable
  variableName?: string;
  variableValue?: unknown;

  // emit_event — `event` (declared above under Trigger) + payload map;
  // payload values support {{var}} refs like db_insert values.
  payload?: Record<string, unknown>;

  // wait_for_event — pauses the run until `event` is emitted on the bus.
  // Optional timeoutMs is surfaced as the pending task's due_at.
  timeoutMs?: number;

  // transform
  transformExpression?: string;

  // custom
  code?: string;

  // AI
  aiPrompt?: string;
  aiModel?: string;

  // ── User task / Approval
  assignee?: string;        // specific user ID or process variable
  assigneeRole?: string;    // role-based assignment
  formBinding?: FormBinding; // form to render for the task
  dueIn?: number;           // minutes until escalation

  // ── Wait
  duration?: number;        // milliseconds

  // Pass-through
  [key: string]: unknown;
}

// ── Workflow Node ──────────────────────────────────────────────────

export interface WorkflowNode {
  id: string;
  type: NodeType;
  position?: { x: number; y: number };
  data: {
    label: string;
    description?: string;
    nodeType?: NodeType;
    config?: NodeConfig;
    /** Input parameters — read from process variables before execution */
    inputParams?: NodeParam[];
    /** Output parameters — written to process variables after execution */
    outputParams?: NodeParam[];
    status?: "idle" | "running" | "completed" | "failed" | "paused";
  };
}

// ── Workflow Edge ──────────────────────────────────────────────────

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  data?: {
    edgeType?: "default" | "then" | "else" | "case";
    label?: string;
    /** Condition expression — if present, edge is only followed when true */
    condition?: string;
  };
}

// ── Workflow Definition ────────────────────────────────────────────

/**
 * Top-level trigger contract (R1/R2). Optional — manual/button workflows
 * have none. Emitted by the Python translator when the plan workflow
 * declares an event or schedule trigger:
 *   {kind:"event",    event:"order.created"} → started by the event bus
 *   {kind:"schedule", cron:"0 9 * * 1"}      → fired by runDueSchedules
 * Legacy `definition.trigger` keeps working; events/triggers.ts
 * normalises both shapes via getTriggerContract().
 */
export type WorkflowTriggerContract =
  | { kind: "event"; event: string }
  | { kind: "schedule"; cron: string };

export interface WorkflowDefinition {
  id: string;
  name: string;
  description?: string;
  /** Optional event/schedule trigger contract — see WorkflowTriggerContract. */
  trigger?: WorkflowTriggerContract;
  /** Process variables — the data context flowing through the workflow */
  processVariables?: ProcessVariable[];
  /**
   * Best-effort cleanup action run when the workflow FAILS (throws out of
   * the node walk). Shape is a plain action config (actionType/table/where/
   * values…) executed as a synthetic node with `{{__error}}` available in
   * ctx.variables. Used by long multi-step workflows (scan → AI → scrapes)
   * to mark their tracking row failed instead of stranding it "processing".
   */
  onFailure?: Record<string, unknown>;
  definition: {
    trigger: WorkflowTrigger;
    nodes: WorkflowNode[];
    edges: WorkflowEdge[];
  };
}

export interface WorkflowTrigger {
  type: TriggerType;
  event?: string;
  schedule?: string;
  /** Input mapping: trigger payload fields → process variables */
  inputMapping?: Record<string, string>;
  config?: Record<string, unknown>;
}

// ── Execution Context ──────────────────────────────────────────────

export interface WorkflowExecutionContext {
  /** The trigger payload */
  input: Record<string, unknown>;
  /** Process variables — accumulated as nodes execute */
  variables: Record<string, unknown>;
  /** Current node being executed */
  currentNodeId?: string;
  /** Execution log */
  log: ExecutionLogEntry[];
  /** User context */
  user?: { id: string; role?: string; email?: string };
}

export interface ExecutionLogEntry {
  nodeId: string;
  nodeLabel: string;
  nodeType: NodeType;
  startedAt: string;
  completedAt?: string;
  status: "running" | "completed" | "failed" | "skipped" | "paused";
  /** Input parameters resolved for this node */
  resolvedInputs?: Record<string, unknown>;
  /** Output parameters produced by this node */
  producedOutputs?: Record<string, unknown>;
  output?: unknown;
  error?: string;
}

export interface WorkflowExecutionResult {
  workflowId: string;
  workflowName: string;
  startedAt: string;
  completedAt?: string;
  status: "completed" | "failed" | "paused";
  log: ExecutionLogEntry[];
  /** Final process variable state */
  output: Record<string, unknown>;
  error?: string;
  /** If paused: which node and what task is pending */
  pausedAt?: string;
  pendingTask?: {
    nodeId: string;
    nodeLabel: string;
    taskType: string;
    assignee?: string;
    assigneeRole?: string;
    formBinding?: FormBinding;
    dueIn?: number;
  };
}

/** Action handler signature */
export type ActionHandler = (
  config: NodeConfig,
  ctx: WorkflowExecutionContext,
) => Promise<unknown>;

// ── Wave 5 Extensions: Parallel Approvers + Conditional Routing + Delegation ──

export type ApproverSelector =
  | { kind: "user"; userId: string }
  | { kind: "role"; role: string }
  | { kind: "field"; path: string }   // e.g. "submittedBy.manager"
  | { kind: "delegated"; backupForUserId: string };

export type StageMode = "any" | "all";  // for parallel approvers

export interface ParallelApproverGroup {
  mode: StageMode;
  approvers: ApproverSelector[];
}

export interface RoutingCondition {
  type: "route";
  if: string;            // expression: e.g. "amount > 5000"
  then: string;          // stage ID to jump to
  else?: string;         // stage ID for else-branch (default: next stage)
}

export interface DelegationRule {
  userId: string;
  delegateTo: string;    // backup user
  validFrom?: string;    // ISO date
  validTo?: string;
}

export interface ReminderConfig {
  afterDays: number;
  channel: "email" | "in-app";
}

export interface EscalationConfig {
  afterDays: number;
  escalateTo: ApproverSelector;
}

// Extend the existing Stage:
export interface StageV2 {
  id: string;
  name: string;
  approvers: ParallelApproverGroup;        // was a single approver
  condition?: RoutingCondition;
  reminders?: ReminderConfig[];
  escalations?: EscalationConfig[];
}

// Workflow now carries delegation rules
export interface WorkflowV2 {
  id: string;
  name: string;
  stages: StageV2[];
  delegations?: DelegationRule[];
}

// ── Legacy aliases for backward compatibility ──
// Existing generated apps that use Stage/Workflow continue to work unchanged.
export type LegacyStage = {
  name: string;
  approver: string;
  condition?: string;
};

export type LegacyWorkflow = {
  id: string;
  name: string;
  stages: LegacyStage[];
};
