/** All type definitions for the workflow engine. */

// --- Status enums (string literal unions) ---

export type WorkflowInstanceStatus =
  | 'created'
  | 'running'
  | 'waiting'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type TaskInstanceStatus =
  | 'pending'
  | 'assigned'
  | 'active'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'cancelled';

export type TaskType =
  | 'user_task'
  | 'service_task'
  | 'timer_event'
  | 'gateway';

export type NodeExecutionStatus =
  | 'started'
  | 'completed'
  | 'failed'
  | 'skipped';

// --- Workflow definition types (match JSON in workflows/*.json) ---

export interface WorkflowNodeConfig {
  type?: string;
  event?: string;
  cron?: string;
  model?: string;
  field?: string;
  path?: string;
  name?: string;
  actionType?: string;
  description?: string;
  expression?: string;
  duration?: string;
  assignType?: string;
  assignTargetName?: string;
  assignVariablePath?: string;
  approvalType?: string;
  slaHours?: number;
  escalateTo?: string;
  pageId?: string;
  // HTTP call
  url?: string;
  method?: string;
  headers?: Record<string, string>;
  body?: Record<string, unknown>;
  // DB query
  query?: string;
  operation?: string;
  where?: Record<string, unknown>;
  data?: Record<string, unknown>;
  // Email
  to?: string;
  subject?: string;
  template?: string;
  // Notification
  title?: string;
  recipient?: string;
  // AI config
  aiInput?: string;
  aiLabels?: string[];
  aiThreshold?: number;
  aiPrompt?: string;
  aiExtractFields?: string[];
  aiContext?: string;
  aiOptions?: string[];
  aiRules?: string;
  aiTone?: string;
  [key: string]: unknown;
}

export interface WorkflowNodeData {
  label?: string;
  config?: WorkflowNodeConfig;
  [key: string]: unknown;
}

export interface WorkflowNode {
  id: string;
  type: string;
  data?: WorkflowNodeData;
  position?: { x: number; y: number };
}

export interface WorkflowEdgeData {
  edgeType?: string;
  label?: string;
  condition?: string;
  [key: string]: unknown;
}

export interface WorkflowEdge {
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
  data?: WorkflowEdgeData;
}

export interface WorkflowDefinitionBody {
  trigger?: Record<string, unknown>;
  steps?: string[];
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export interface WorkflowDefinition {
  id: string;
  name: string;
  description?: string;
  definition: WorkflowDefinitionBody;
}

// --- Decision table types ---

export interface DecisionTableInput {
  id: string;
  name: string;
  label?: string;
  type: string;
  variableBinding?: string;
}

export interface DecisionTableOutput {
  id: string;
  name: string;
  label?: string;
  type: string;
}

export interface DecisionTableRule {
  id: string;
  inputEntries: string[];
  outputEntries: string[];
  annotation?: string;
}

export interface DecisionTableDefinition {
  id: string;
  name: string;
  hitPolicy: 'U' | 'F' | 'A' | 'P' | 'C' | 'R';
  inputs: DecisionTableInput[];
  outputs: DecisionTableOutput[];
  rules: DecisionTableRule[];
}

// --- Runtime record types (match Drizzle table inferred types) ---

export interface WorkflowInstanceRecord {
  id: string;
  workflowId: string;
  workflowName: string;
  status: WorkflowInstanceStatus;
  currentNodeIds: string[];
  variables: Record<string, unknown>;
  initiatedBy: string | null;
  errorMessage: string | null;
  startedAt: Date | null;
  completedAt: Date | null;
  createdAt: Date;
  updatedAt: Date;
}

export interface TaskInstanceRecord {
  id: string;
  workflowInstanceId: string;
  nodeId: string;
  nodeLabel: string | null;
  taskType: TaskType;
  status: TaskInstanceStatus;
  assigneeId: string | null;
  assigneeType: string | null;
  inputData: Record<string, unknown>;
  outputData: Record<string, unknown>;
  dueAt: Date | null;
  completedAt: Date | null;
  errorMessage: string | null;
  createdAt: Date;
  updatedAt: Date;
}

export interface ExecutionLogRecord {
  id: string;
  workflowInstanceId: string;
  nodeId: string;
  nodeType: string;
  nodeLabel: string | null;
  status: NodeExecutionStatus;
  inputSnapshot: Record<string, unknown> | null;
  outputSnapshot: Record<string, unknown> | null;
  errorMessage: string | null;
  startedAt: Date;
  completedAt: Date | null;
  durationMs: number | null;
}
