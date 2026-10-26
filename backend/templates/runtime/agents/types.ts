/**
 * Agent runtime — shared types. Forge runtime — do not remove.
 *
 * An agent is DATA: `src/agents/definitions/<id>.json` holds one
 * `AgentRuntimeConfig`, compiled by the platform (services/agent_runtime_config.py)
 * from the node graph the Agent Builder saves. The runtime in this directory
 * reads it and runs the loop; there is no per-agent code to generate.
 */

import type { UsageStore } from "./limits";

export type ToolKind = "data" | "api" | "workflow" | "mcp" | "ai_action" | "function" | "handoff";

export type DataOperation = "list" | "get" | "create" | "update" | "delete";

export interface JsonSchemaObject {
  type: "object";
  properties: Record<string, unknown>;
  required?: string[];
  additionalProperties?: boolean;
}

export interface AgentToolSpec {
  name: string;
  description: string;
  kind: ToolKind;
  /** What the MODEL may supply. Anything else comes from the spec. */
  inputSchema: JsonSchemaObject;
  /** The person must be signed in for this tool to run. Default true. */
  requireAuth?: boolean;
  /** This tool changes data: it is held until the person has agreed (see confirm.ts). Set by the compiler. */
  confirm?: boolean;
  /** "10/min" | "5/hour" | "2/sec" — per person, per tool. */
  rateLimit?: string;
  /** Keep only these keys of the result (applied to arrays element-wise). */
  responseFilter?: string[];

  // kind: "data" — the app's own /api/data/<entity> route
  entity?: string;
  operation?: DataOperation;

  // kind: "api" — any route of this app
  endpoint?: string;
  method?: string;
  defaultParams?: Record<string, unknown>;

  // kind: "workflow"
  workflowId?: string;

  // kind: "mcp"
  mcpServerId?: string;
  mcpToolName?: string;
  /** tool argument -> "{{input.field}}" | literal. Resolved against the model's input. */
  argsMapping?: Record<string, string>;

  // kind: "ai_action"
  aiAction?: "identify_product" | "classify" | "extract" | "generate";
  aiConfig?: Record<string, unknown>;

  // kind: "function" — the compiled tool module under src/agents/tools/
  /** File stem under src/agents/tools/, registered in src/agents/registry.ts. */
  handler?: string;
}

export interface InputGuardrails {
  maxLength: number;
  /** Regex sources, matched case-insensitively. */
  blockPatterns: string[];
  requireAuth: boolean;
}

export interface OutputGuardrails {
  maxTokens?: number;
  blockPatterns: string[];
  contentFilter: "none" | "standard" | "strict";
}

/** A condition over tool results that must hold before an answer is shown,
 *  e.g. `identify_product.confidence >= 0.5` (FEEL-lite, tool names are variables). */
export interface OutputRule {
  name: string;
  expression: string;
  /** What the person is told when the rule fails. */
  message?: string;
}

/** How much one person may use the assistants. 0 = no limit; anything left out takes the default (limits.ts). */
export interface Limits {
  perMinute: number;
  perHour: number;
  tokensPerDay: number;
}

export interface GuardrailSpec {
  input: InputGuardrails;
  output: OutputGuardrails;
  outputRules: OutputRule[];
  limits?: Partial<Limits>;
}

/** An action waiting for the person's yes: made on `turn`, released only on the turn after. */
export interface Hold {
  /** What the person's button press names. Made when the hold is made; a hold kept from before this existed has none and can only be asked again. */
  id?: string;
  tool: string;
  key: string;
  summary: string;
  at: number;
  turn: number;
}

/** The person's answer to one held change: a button pressed in the chat, never words they typed. */
export interface ConfirmSignal {
  holdId: string;
  decision: "confirm" | "cancel";
}

/** What a conversation remembers between requests about changes it has held back. */
export interface ConfirmState {
  /** How many messages the person has sent here (this one included, once counted). */
  turn: number;
  holds: Hold[];
}

export interface MemorySpec {
  type: "conversation" | "key_value" | "vector";
  /** Recent turns replayed to the model. */
  maxMessages: number;
  /** When the stored turns exceed this, the oldest are folded into a summary. */
  summarizeAfter: number;
}

export interface AgentUiSpec {
  title: string;
  subtitle?: string;
  welcomeMessage?: string;
  suggestedQuestions?: string[];
  position: "bottom-right" | "bottom-left" | "full-page";
}

export interface AgentRuntimeConfig {
  id: string;
  name: string;
  description?: string;
  enabled: boolean;
  model: { name?: string; maxTokens: number; temperature?: number };
  systemPrompt: string;
  tools: AgentToolSpec[];
  memory: MemorySpec;
  guardrails: GuardrailSpec;
  /** The most model↔tool rounds one message may take. */
  maxTurns: number;
  ui: AgentUiSpec;
  /** Carried through from a router node. Not executed yet. */
  router?: Record<string, unknown> | null;
  /** The human-handoff box: who handles it, how it is assigned, what is asked, who is told. */
  handoff?: HandoffSpec | null;
}

// ── human handoff ─────────────────────────────────────────────────────────

export type HandoffStatus = "open" | "claimed" | "resolved";
export type HandoffUrgency = "low" | "normal" | "urgent";

export interface HandoffSpec {
  handlers: { roles: string[]; people: Array<{ id: string; name?: string }> };
  assignment: "queue" | "round_robin" | "owner";
  ownerId?: string;
  /** What the assistant asks the person before it hands over. */
  questions: string[];
  /** In-app notification (the bell) is the default; email is optional and never required. */
  notify: { inApp: boolean; email: boolean; emailUrgentOnly: boolean };
  keywords: string[];
}

export interface Person {
  id: string;
  name?: string | null;
  email?: string | null;
  role?: string | null;
}

export interface HandoffRecord {
  id: string;
  /** Short, readable, quotable: HO-7K3Q2. */
  ref: string;
  conversationId: string;
  agentId: string;
  requestedById: string;
  requestedByName?: string | null;
  reason: string;
  urgency: HandoffUrgency;
  contact?: string | null;
  /** The last few messages, so whoever takes it has the context without opening the chat. */
  summary?: string | null;
  status: HandoffStatus;
  assignedToId?: string | null;
  assignedToName?: string | null;
  /** The organisation the person who asked was acting in; the inbox only shows a handoff to its own organisation. */
  orgId?: string | null;
  resolutionNote?: string | null;
  createdAt: string | Date;
  claimedAt?: string | Date | null;
  resolvedAt?: string | Date | null;
}

export interface HandoffStore {
  create(h: Omit<HandoffRecord, "id" | "ref" | "createdAt" | "status">): Promise<HandoffRecord>;
  /** The conversation's handoff that is not resolved yet, if any. */
  openFor(conversationId: string): Promise<HandoffRecord | null>;
  /** How many unresolved handoffs each of these people holds. */
  openCounts(userIds: string[]): Promise<Record<string, number>>;
}

/** Everything a handoff touches outside the loop. Each side effect after the record is saved is best-effort. */
export interface HandoffDeps {
  store: HandoffStore;
  /** People who hold any of these roles, in this organisation when one is given. */
  people(roles: string[], orgId?: string | null): Promise<Person[]>;
  /** One in-app notification (the bell). A userId addresses a person; a role (no userId) addresses everyone in it. */
  notify(n: { title: string; message: string; userId?: string | null; role?: string | null; entityId?: string }): Promise<void>;
  /** Optional. `sent: false` with a reason is the normal answer from an app with no email set up. */
  email?(to: string, subject: string, body: string): Promise<{ sent: boolean; reason?: string }>;
  /** The last messages of the conversation, as text. Optional. */
  snapshot?(conversationId: string): Promise<string>;
}

// ── conversation ──────────────────────────────────────────────────────────

export interface StoredMessage {
  id?: string;
  /** "human" is a person on the team writing into a conversation that was handed to them. */
  role: "user" | "assistant" | "human";
  content: string;
  toolCalls?: ToolCallRecord[] | null;
  tokenCount?: number | null;
  createdAt?: Date | string | null;
}

export interface ToolCallRecord {
  name: string;
  input: unknown;
  result?: unknown;
  error?: string;
}

export interface ConversationStore {
  /** A conversation the person owns, or null (also null for someone else's). */
  getConversation(id: string, userId: string): Promise<{ id: string; summary: string | null } | null>;
  createConversation(agentId: string, userId: string): Promise<string>;
  /** Oldest first. */
  listMessages(conversationId: string): Promise<StoredMessage[]>;
  /** Resolves to the saved message's id when the store knows it (the chat hands it to the widget for thumbs up/down). */
  saveMessage(conversationId: string, msg: StoredMessage): Promise<string | void>;
  setSummary(conversationId: string, summary: string, dropMessageIds: string[]): Promise<void>;
  /** Held changes and the turn count. Optional: a store without them can never release a held change. */
  getState?(conversationId: string): Promise<ConfirmState>;
  setState?(conversationId: string, state: ConfirmState): Promise<void>;
}

// ── model ─────────────────────────────────────────────────────────────────

export type ModelBlock =
  | { type: "text"; text: string }
  | { type: "tool_use"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; tool_use_id: string; content: string; is_error?: boolean };

export interface ModelMessage {
  role: "user" | "assistant";
  content: string | ModelBlock[];
}

export interface ModelToolDef {
  name: string;
  description: string;
  input_schema: JsonSchemaObject;
}

export interface ModelRequest {
  model?: string;
  maxTokens: number;
  temperature?: number;
  system: string;
  messages: ModelMessage[];
  tools: ModelToolDef[];
}

export interface ModelResult {
  content: ModelBlock[];
  usage: { inputTokens: number; outputTokens: number };
  /** The model that actually answered (what the provider reports). Absent from a fake or an older caller. */
  model?: string;
}

// ── the run ───────────────────────────────────────────────────────────────

export interface AgentUser {
  id: string;
  role?: string;
  email?: string;
  /** The organisation the person acts in (the session's active one). Absent in an app of one organisation. */
  orgId?: string | null;
}

export type AgentEvent =
  | { type: "text"; content: string }
  | { type: "tool_call"; id: string; tool: string; input: unknown }
  | { type: "tool_result"; id: string; tool: string; ok: boolean; result?: unknown; error?: string }
  /** `replacement` (output stage): text already streamed is to be replaced with it. */
  | { type: "blocked"; reason: string; stage: "input" | "output"; replacement?: string }
  /** The conversation is with a person now (or was): `status` says where it stands. */
  | { type: "handoff"; ref: string; status: HandoffStatus; note?: string | null }
  /** `messageId` is the saved assistant message (null when the turn saved none): what a thumbs up or down is sent against. */
  | { type: "done"; conversationId: string; tokens: { input: number; output: number }; turns: number; messageId?: string | null }
  | { type: "error"; message: string };

export interface ToolContext {
  user: AgentUser | null;
  /** The conversation this call belongs to, the agent running it and its handoff settings (for request_human). */
  conversationId?: string;
  agentId?: string;
  handoff?: HandoffSpec | null;
  /** The caller's session cookie, forwarded to the app's own routes so access
   *  control is the app's, not the agent's. */
  cookie: string;
  origin: string;
}

/** Where the runtime is in its work: for whoever is watching (the builder's live view). Never needed to run. */
export type TraceEvent =
  | { type: "phase"; phase: "input_check"; ok: boolean; reason?: string }
  | { type: "phase"; phase: "memory"; messages: number; summarised: boolean }
  | { type: "phase"; phase: "with_person"; ref: string }
  | { type: "phase"; phase: "output_check"; ok: boolean; reason?: string };

// ── what each turn cost, and how it went ─────────────────────────────────

export type TurnStatus = "ok" | "error" | "blocked";

/** One tool call in a turn: its name, whether it worked, how long it took. Never what it returned. */
export interface TurnToolStat {
  name: string;
  ok: boolean;
  ms: number;
}

/** What is kept about one turn (see db/forge-agent-turns.schema.ts). No message text, no tool results. */
export interface TurnRecord {
  /** Empty when the message was refused before a conversation existed. */
  conversationId: string;
  agentId: string;
  userId: string;
  model: string | null;
  inputTokens: number;
  outputTokens: number;
  ms: number;
  status: TurnStatus;
  /** Why it failed or was blocked, as a short sentence. */
  error: string | null;
  toolCalls: number;
  toolErrors: number;
  /** At most 20 entries. */
  toolStats: TurnToolStat[];
  handedOff: boolean;
  assistantMessageId: string | null;
  /** The person's role name when they were signed in. Sent to the platform's insights, so it can split numbers by role. */
  userRole?: string | null;
  /** 1 = the first message of its conversation; null when the runtime could not say (the store counts then). */
  turnNumber?: number | null;
  /** The first words of what the person wrote: only when FORGE_INSIGHTS_INCLUDE_TEXT=1, otherwise always null. */
  userMessage?: string | null;
}

export interface TurnStore {
  record(turn: TurnRecord): Promise<void>;
}

export interface AgentDeps {
  callModel(req: ModelRequest, onText: (chunk: string) => void): Promise<ModelResult>;
  /** `scope` holds each tool's latest result by tool name, so a later tool's
   *  `argsMapping` can read an earlier one (`{{identify_product.brand}}`). */
  runTool(
    spec: AgentToolSpec,
    input: Record<string, unknown>,
    ctx: ToolContext,
    scope: Record<string, unknown>,
  ): Promise<unknown>;
  store: ConversationStore;
  /** Absent in an app with no handoff table: nothing is ever "handed over" there. */
  handoffs?: {
    openFor(conversationId: string): Promise<HandoffRecord | null>;
    /** The person wrote to a conversation that is with someone: tell them (best-effort, may be absent). */
    customerWrote?(handoff: HandoffRecord, text: string): Promise<void>;
  };
  /** Usage counts for the limits. Absent (or failing: no table yet) → not limited. */
  usage?: UsageStore;
  /** Where each turn's cost and outcome is kept. Absent (or failing: no table yet) → nothing is recorded, the chat is unaffected. */
  turns?: TurnStore;
  /** Told where the run is (checks, memory, answer check). Absent in a normal chat; the live view supplies it. */
  trace?: (e: TraceEvent) => void;
  /** FEEL-lite. Absent → output rules are skipped. */
  evalExpression?: (expression: string, scope: Record<string, unknown>) => unknown;
  now?: () => number;
}

export interface AgentRunInput {
  message: string;
  /** Set only when the person pressed Go ahead or Cancel on a held change. Typed words are never a confirmation. */
  confirm?: ConfirmSignal | null;
  conversationId: string | null;
  user: AgentUser | null;
  cookie: string;
  origin: string;
}
