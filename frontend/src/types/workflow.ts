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

export const NODE_CATEGORIES: NodeCategory[] = [
  {
    label: "Triggers",
    nodes: [
      { id: "trigger-manual", type: "trigger", label: "Manual", icon: "Hand", description: "User/API triggered", gradient: "bg-gradient-to-br from-orange-400 to-orange-600", defaultConfig: { type: "manual" } },
      { id: "trigger-webhook", type: "trigger", label: "Webhook", icon: "Webhook", description: "Webhook/message trigger", gradient: "bg-gradient-to-br from-purple-400 to-purple-600", defaultConfig: { type: "webhook" } },
      { id: "trigger-schedule", type: "trigger", label: "Schedule", icon: "Calendar", description: "Scheduled trigger", gradient: "bg-gradient-to-br from-sky-400 to-sky-600", defaultConfig: { type: "schedule" } },
      { id: "trigger-api", type: "trigger", label: "API Event", icon: "Zap", description: "Broadcast signal trigger", gradient: "bg-gradient-to-br from-rose-400 to-rose-600", defaultConfig: { type: "api_event" } },
      { id: "trigger-db", type: "trigger", label: "DB Change", icon: "Database", description: "Data condition trigger", gradient: "bg-gradient-to-br from-amber-400 to-amber-600", defaultConfig: { type: "db_change" } },
    ],
  },
  {
    label: "Actions",
    nodes: [
      { id: "action-custom", type: "action", label: "Custom Action", icon: "Play", description: "Execute custom logic", gradient: "bg-gradient-to-br from-teal-400 to-teal-600", defaultConfig: { actionType: "custom" } },
      { id: "action-db", type: "action", label: "DB Query", icon: "Database", description: "Database operation", gradient: "bg-gradient-to-br from-cyan-400 to-cyan-600", defaultConfig: { actionType: "db_query" } },
      { id: "action-http", type: "action", label: "HTTP Call", icon: "Globe", description: "External API call", gradient: "bg-gradient-to-br from-indigo-400 to-indigo-600", defaultConfig: { actionType: "http_call" } },
      { id: "action-email", type: "action", label: "Send Email", icon: "Mail", description: "Email notification", gradient: "bg-gradient-to-br from-blue-400 to-blue-600", defaultConfig: { actionType: "send_email" } },
      { id: "action-notify", type: "action", label: "Notification", icon: "Bell", description: "In-app notification", gradient: "bg-gradient-to-br from-orange-400 to-amber-500", defaultConfig: { actionType: "send_notification" } },
      { id: "action-db-insert", type: "action", label: "Insert Record", icon: "Database", description: "Create a database row", gradient: "bg-gradient-to-br from-green-400 to-green-600", defaultConfig: { actionType: "db_insert" } },
      { id: "action-db-update", type: "action", label: "Update Record", icon: "Database", description: "Update a database row", gradient: "bg-gradient-to-br from-lime-400 to-lime-600", defaultConfig: { actionType: "db_update" } },
      { id: "action-db-delete", type: "action", label: "Delete Record", icon: "Database", description: "Delete a database row", gradient: "bg-gradient-to-br from-red-400 to-rose-600", defaultConfig: { actionType: "db_delete" } },
      { id: "action-set-variable", type: "action", label: "Set Variable", icon: "Hash", description: "Set a process variable", gradient: "bg-gradient-to-br from-slate-400 to-slate-600", defaultConfig: { actionType: "set_variable" } },
      { id: "action-transform", type: "action", label: "Transform", icon: "Hash", description: "Transform/map data", gradient: "bg-gradient-to-br from-stone-400 to-stone-600", defaultConfig: { actionType: "transform" } },
      { id: "action-generate-document", type: "action", label: "Generate Document", icon: "FileText", description: "Generate a document", gradient: "bg-gradient-to-br from-emerald-400 to-teal-600", defaultConfig: { actionType: "generate_document" } },
      { id: "action-mcp-tool", type: "action", label: "MCP Tool Call", icon: "Plug", description: "Call a tool on a configured MCP server", gradient: "bg-gradient-to-br from-violet-400 to-indigo-600", defaultConfig: { actionType: "mcp_tool_call" } },
      { id: "action-emit-event", type: "action", label: "Emit Event", icon: "Zap", description: "Publish a domain event on the bus", gradient: "bg-gradient-to-br from-yellow-400 to-orange-600", defaultConfig: { actionType: "emit_event" } },
      { id: "action-wait-event", type: "action", label: "Wait for Event", icon: "Clock", description: "Pause until an event is emitted", gradient: "bg-gradient-to-br from-sky-400 to-indigo-600", defaultConfig: { actionType: "wait_for_event" } },
    ],
  },
  {
    label: "Flow Control",
    nodes: [
      { id: "condition", type: "condition", label: "Condition", icon: "GitBranch", description: "Branch on expression", gradient: "bg-gradient-to-br from-purple-500 to-purple-700" },
      { id: "exclusive_gateway", type: "exclusive_gateway", label: "Exclusive Gateway", icon: "GitBranch", description: "Branch on one condition", gradient: "bg-gradient-to-br from-purple-500 to-fuchsia-700" },
      { id: "parallel_gateway", type: "parallel_gateway", label: "Parallel Gateway", icon: "Split", description: "Split/merge parallel paths", gradient: "bg-gradient-to-br from-cyan-500 to-blue-700" },
      { id: "fork", type: "fork", label: "Fork", icon: "Split", description: "Fork into parallel branches", gradient: "bg-gradient-to-br from-teal-500 to-cyan-700" },
      { id: "join", type: "join", label: "Join", icon: "GitMerge", description: "Join parallel branches", gradient: "bg-gradient-to-br from-blue-500 to-indigo-700" },
      { id: "decision", type: "decision", label: "Decision Table", icon: "Table2", description: "Rule-based routing", gradient: "bg-gradient-to-br from-emerald-500 to-green-700" },
      { id: "wait", type: "wait", label: "Wait", icon: "Clock", description: "Time-based delay", gradient: "bg-gradient-to-br from-amber-500 to-amber-700" },
      { id: "end", type: "end", label: "End", icon: "Square", description: "Workflow end", gradient: "bg-gradient-to-br from-red-400 to-red-600" },
    ],
  },
  {
    label: "Human-in-Loop",
    nodes: [
      { id: "user_task", type: "user_task", label: "User Task", icon: "ClipboardCheck", description: "Wait for a person to complete a step", gradient: "bg-gradient-to-br from-blue-500 to-cyan-700" },
      { id: "assignment", type: "assignment", label: "Assignment", icon: "UserPlus", description: "Manual user task", gradient: "bg-gradient-to-br from-blue-500 to-blue-700" },
      { id: "approval", type: "approval", label: "Approval", icon: "CheckCircle", description: "Review and approve", gradient: "bg-gradient-to-br from-indigo-500 to-indigo-700" },
      { id: "task_pool", type: "task_pool", label: "Task Pool", icon: "Users", description: "Distributed task queue", gradient: "bg-gradient-to-br from-sky-500 to-sky-700" },
      { id: "escalation", type: "escalation", label: "Escalation", icon: "ArrowUpCircle", description: "Priority escalation", gradient: "bg-gradient-to-br from-rose-500 to-rose-700" },
    ],
  },
  {
    label: "AI Nodes",
    nodes: [
      { id: "ai_classify", type: "ai_classify", label: "AI Classify", icon: "Brain", description: "Auto-categorize data", gradient: "bg-gradient-to-br from-violet-500 to-violet-700" },
      { id: "ai_extract", type: "ai_extract", label: "AI Extract", icon: "ScanText", description: "Extract structured data", gradient: "bg-gradient-to-br from-fuchsia-500 to-fuchsia-700" },
      { id: "ai_decide", type: "ai_decide", label: "AI Decision", icon: "GitBranch", description: "AI-powered routing", gradient: "bg-gradient-to-br from-purple-500 to-violet-700" },
      { id: "ai_generate", type: "ai_generate", label: "AI Generate", icon: "Sparkles", description: "Generate content", gradient: "bg-gradient-to-br from-pink-500 to-pink-700" },
    ],
  },
];

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
  | "custom";

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
