// ---------------------------------------------------------------------------
// Agent Node Types
// ---------------------------------------------------------------------------

export type AgentNodeType =
  | "system_prompt"
  | "tool"
  | "guardrail"
  | "memory"
  | "human_handoff"
  | "router";

export const AGENT_NODE_CATEGORIES = [
  {
    label: "Core",
    nodes: [
      { type: "system_prompt" as AgentNodeType, label: "System Prompt", icon: "Brain", description: "Define the agent's persona and instructions" },
      { type: "tool" as AgentNodeType, label: "Tool", icon: "Wrench", description: "API call, DB query, or function" },
    ],
  },
  {
    label: "Safety",
    nodes: [
      { type: "guardrail" as AgentNodeType, label: "Guardrail", icon: "Shield", description: "Input/output filtering and content policy" },
    ],
  },
  {
    label: "Memory",
    nodes: [
      { type: "memory" as AgentNodeType, label: "Memory", icon: "DatabaseZap", description: "Conversation, vector, or key-value store" },
    ],
  },
  {
    label: "Flow",
    nodes: [
      { type: "router" as AgentNodeType, label: "Router", icon: "GitFork", description: "Route to different paths by intent or condition" },
      { type: "human_handoff" as AgentNodeType, label: "Human Handoff", icon: "UserCheck", description: "Escalate to a human operator" },
    ],
  },
] as const;

// ---------------------------------------------------------------------------
// Node Configs
// ---------------------------------------------------------------------------

export interface SystemPromptConfig {
  prompt?: string;
  temperature?: number;
  model?: string;
  max_tokens?: number;
  is_entry_point?: boolean;
}

export type ToolType =
  | "workflow"      // call a project workflow (typed inputs auto-populated)
  | "data_engine"   // hit /api/data/<entity> — CRUD without a workflow
  | "api_call"      // arbitrary HTTP (free-text URL)
  | "db_query"      // raw SQL
  | "function"      // inline TypeScript
  | "external"      // third-party HTTP with its own auth
  | "mcp";          // call a tool exposed by a registered MCP server

export type DataEngineOperation = "list" | "get" | "create" | "update" | "delete";

export interface ToolParameter {
  name: string;
  type: string;
  required: boolean;
  description?: string;
}

export interface ToolConfig {
  tool_name?: string;
  tool_type?: ToolType;
  endpoint?: string;
  method?: string;
  query?: string;
  code?: string;
  parameters?: ToolParameter[];
  response_schema?: string;
  description?: string;
  // Populated when tool_type=workflow — the workflow the picker resolved to.
  workflow_id?: string;
  // Populated when tool_type=data_engine.
  entity?: string;
  operation?: DataEngineOperation;
  // Populated when tool_type=mcp — the org-registered MCP server + tool the
  // picker resolved to, plus optional FEEL-lite expressions binding each
  // tool argument to another node's output (e.g. "{{scan_events.image_id}}").
  mcp_server_id?: string;
  mcp_tool_name?: string;
  args_mapping?: Record<string, string>;
}

// ---------------------------------------------------------------------------
// Agent-level I/O schema — what a caller supplies and what the agent returns.
// Stored on AgentDefinition.config so it round-trips with the definition.
// ---------------------------------------------------------------------------
export interface AgentIOField {
  name: string;
  type: "string" | "number" | "boolean" | "object" | "array" | "date" | "uuid";
  required: boolean;
  description?: string;
}

export type GuardrailType = "input_filter" | "output_filter" | "both";

export interface GuardrailRule {
  id: string;
  name: string;
  type: "block_topics" | "pii_redaction" | "content_policy" | "custom";
  expression?: string;
}

export interface GuardrailConfig {
  guardrail_type?: GuardrailType;
  rules?: GuardrailRule[];
  custom_expression?: string;
}

export type MemoryType = "conversation" | "vector" | "key_value";

export interface MemoryConfig {
  memory_type?: MemoryType;
  capacity?: number;
  ttl_seconds?: number;
  embedding_model?: string;
  similarity_threshold?: number;
}

export interface HumanHandoffConfig {
  conditions?: {
    sentiment_threshold?: number;
    keyword_triggers?: string[];
    explicit_request?: boolean;
  };
  target?: {
    type?: "queue" | "email" | "webhook";
    value?: string;
  };
  context_fields?: string[];
}

export type RoutingStrategy = "intent_classification" | "condition" | "round_robin" | "fallback";

export interface RouteDefinition {
  id: string;
  label: string;
  target_node_id?: string;
  condition?: string;
}

export interface RouterConfig {
  strategy?: RoutingStrategy;
  routes?: RouteDefinition[];
  default_route?: string;
}

// ---------------------------------------------------------------------------
// Agent Node Data (for React Flow)
// ---------------------------------------------------------------------------

export type AgentNodeConfig =
  | SystemPromptConfig
  | ToolConfig
  | GuardrailConfig
  | MemoryConfig
  | HumanHandoffConfig
  | RouterConfig;

export interface AgentNodeData extends Record<string, unknown> {
  label: string;
  nodeType: AgentNodeType;
  config: AgentNodeConfig;
}

// ---------------------------------------------------------------------------
// Agent Edge Data
// ---------------------------------------------------------------------------

export type AgentEdgeType = "default" | "route" | "fallback";

export interface AgentEdgeData extends Record<string, unknown> {
  edgeType: AgentEdgeType;
  label?: string;
}

// ---------------------------------------------------------------------------
// Serialized formats
// ---------------------------------------------------------------------------

export interface AgentNodeSerialized {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: AgentNodeData;
}

export interface AgentEdgeSerialized {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  data?: AgentEdgeData;
}

// ---------------------------------------------------------------------------
// Agent Definition
// ---------------------------------------------------------------------------

export interface AgentDefinition {
  id: string;
  name: string;
  description?: string;
  nodes: AgentNodeSerialized[];
  edges: AgentEdgeSerialized[];
  config?: {
    max_turns?: number;
    timeout_seconds?: number;
    input_schema?: AgentIOField[];
    output_schema?: AgentIOField[];
  };
}

// ---------------------------------------------------------------------------
// Agent List Item (from API)
// ---------------------------------------------------------------------------

export interface AgentListItem {
  id: string;
  name: string;
  description: string | null;
  node_count: number;
}

// ---------------------------------------------------------------------------
// Agent Templates
// ---------------------------------------------------------------------------

export interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  nodes: AgentNodeSerialized[];
  edges: AgentEdgeSerialized[];
}

// ---------------------------------------------------------------------------
// Test Console
// ---------------------------------------------------------------------------

export interface AgentTestMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

export interface NodeTraceEntry {
  node_id: string;
  node_type: AgentNodeType;
  label: string;
  started_at: string;
  completed_at?: string;
  status: "running" | "completed" | "failed" | "skipped";
  result?: Record<string, unknown>;
  error?: string;
  duration_ms?: number;
  tokens_used?: number;
}

export interface AgentTestResult {
  response: string;
  trace: NodeTraceEntry[];
  total_tokens: number;
  total_duration_ms: number;
}
