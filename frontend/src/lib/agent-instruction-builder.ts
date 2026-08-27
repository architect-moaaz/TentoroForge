import type {
  AgentDefinition,
  AgentNodeSerialized,
  AgentEdgeSerialized,
  AgentNodeType,
  AgentNodeConfig,
  SystemPromptConfig,
  ToolConfig,
  GuardrailConfig,
  MemoryConfig,
  HumanHandoffConfig,
  RouterConfig,
} from "@/types/agent-builder";

/**
 * Converts a visual agent definition into a natural-language instruction
 * for the code_editor agent to implement inside the generated application.
 */
export function buildAgentInstruction(agent: AgentDefinition): string {
  const { name, description, nodes, edges } = agent;

  const parts: string[] = [
    `Implement AI agent "${name}" in the generated application.`,
    "",
  ];

  if (description) {
    parts.push(`Description: ${description}`, "");
  }

  // ── Agent Nodes ────────────────────────────────────────
  parts.push(nodesSection(nodes));

  // ── Connections ────────────────────────────────────────
  parts.push(connectionsSection(nodes, edges));

  // ── Implementation Requirements ────────────────────────
  parts.push(requirementsSection(nodes));

  return parts.join("\n");
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function nodesSection(nodes: AgentNodeSerialized[]): string {
  const lines: string[] = ["## Agent Nodes"];

  for (const node of nodes) {
    const { data } = node;
    const { label, nodeType, config } = data;
    lines.push(`\n### [${nodeType}] ${label} (id: ${node.id})`);
    lines.push(nodeConfigDescription(nodeType, config));
  }

  lines.push("");
  return lines.join("\n");
}

function nodeConfigDescription(
  nodeType: AgentNodeType,
  config: AgentNodeConfig,
): string {
  const lines: string[] = [];

  switch (nodeType) {
    case "system_prompt": {
      const c = config as SystemPromptConfig;
      if (c.prompt) lines.push(`  System prompt: ${c.prompt.slice(0, 300)}${c.prompt.length > 300 ? "..." : ""}`);
      if (c.model) lines.push(`  Model: ${c.model}`);
      if (c.temperature !== undefined) lines.push(`  Temperature: ${c.temperature}`);
      if (c.max_tokens) lines.push(`  Max tokens: ${c.max_tokens}`);
      if (c.is_entry_point) lines.push(`  This is the entry point of the agent`);
      break;
    }

    case "tool": {
      const c = config as ToolConfig;
      if (c.tool_name) lines.push(`  Tool name: ${c.tool_name}`);
      if (c.tool_type) lines.push(`  Type: ${c.tool_type}`);
      if (c.description) lines.push(`  Description: ${c.description}`);
      if (c.tool_type === "api_call" || c.tool_type === "external") {
        if (c.endpoint) lines.push(`  Endpoint: ${c.method || "GET"} ${c.endpoint}`);
      }
      if (c.tool_type === "db_query" && c.query) {
        lines.push(`  Query: ${c.query}`);
      }
      if (c.tool_type === "function" && c.code) {
        lines.push(`  Implementation: ${c.code.slice(0, 200)}`);
      }
      if (c.parameters && c.parameters.length > 0) {
        lines.push(`  Parameters:`);
        for (const p of c.parameters) {
          lines.push(`    - ${p.name}: ${p.type}${p.required ? " (required)" : ""}${p.description ? ` — ${p.description}` : ""}`);
        }
      }
      if (c.response_schema) lines.push(`  Response schema: ${c.response_schema}`);
      break;
    }

    case "guardrail": {
      const c = config as GuardrailConfig;
      if (c.guardrail_type) lines.push(`  Filter type: ${c.guardrail_type}`);
      if (c.rules && c.rules.length > 0) {
        lines.push(`  Rules:`);
        for (const r of c.rules) {
          lines.push(`    - ${r.name} (${r.type})${r.expression ? `: ${r.expression}` : ""}`);
        }
      }
      if (c.custom_expression) lines.push(`  Custom expression: ${c.custom_expression}`);
      break;
    }

    case "memory": {
      const c = config as MemoryConfig;
      if (c.memory_type) lines.push(`  Memory type: ${c.memory_type}`);
      if (c.capacity) lines.push(`  Capacity: ${c.capacity}`);
      if (c.ttl_seconds) lines.push(`  TTL: ${c.ttl_seconds} seconds`);
      if (c.memory_type === "vector") {
        if (c.embedding_model) lines.push(`  Embedding model: ${c.embedding_model}`);
        if (c.similarity_threshold !== undefined) lines.push(`  Similarity threshold: ${c.similarity_threshold}`);
      }
      break;
    }

    case "human_handoff": {
      const c = config as HumanHandoffConfig;
      const cond = c.conditions || {};
      if (cond.sentiment_threshold !== undefined) lines.push(`  Sentiment threshold: ${cond.sentiment_threshold}`);
      if (cond.keyword_triggers?.length) lines.push(`  Keyword triggers: ${cond.keyword_triggers.join(", ")}`);
      if (cond.explicit_request) lines.push(`  Trigger on explicit request: yes`);
      const target = c.target || {};
      if (target.type) lines.push(`  Handoff to: ${target.type}${target.value ? ` (${target.value})` : ""}`);
      if (c.context_fields?.length) lines.push(`  Pass context: ${c.context_fields.join(", ")}`);
      break;
    }

    case "router": {
      const c = config as RouterConfig;
      if (c.strategy) lines.push(`  Strategy: ${c.strategy}`);
      if (c.routes && c.routes.length > 0) {
        lines.push(`  Routes:`);
        for (const r of c.routes) {
          lines.push(`    - ${r.label}${r.condition ? ` (condition: ${r.condition})` : ""}`);
        }
      }
      if (c.default_route) lines.push(`  Default route: ${c.default_route}`);
      break;
    }
  }

  return lines.join("\n");
}

function connectionsSection(
  nodes: AgentNodeSerialized[],
  edges: AgentEdgeSerialized[],
): string {
  if (edges.length === 0) return "";

  const lines: string[] = ["## Connections"];

  for (const edge of edges) {
    const edgeType = edge.data?.edgeType || "default";
    const sourceNode = nodes.find((n) => n.id === edge.source);
    const targetNode = nodes.find((n) => n.id === edge.target);
    const sourceName = sourceNode?.data.label || edge.source;
    const targetName = targetNode?.data.label || edge.target;
    const label = edge.data?.label ? ` [${edge.data.label}]` : "";
    lines.push(`- ${sourceName} → ${targetName} (${edgeType})${label}`);
  }

  lines.push("");
  return lines.join("\n");
}

function requirementsSection(nodes: AgentNodeSerialized[]): string {
  const lines: string[] = ["## Implementation Requirements"];

  lines.push("1. Create an agent service class (src/agents/agent-service.ts) that orchestrates the node graph");
  lines.push("2. Create an API route POST /api/agent/chat for interacting with the agent");

  const hasSystemPrompt = nodes.some((n) => n.data.nodeType === "system_prompt");
  const hasTools = nodes.some((n) => n.data.nodeType === "tool");
  const hasGuardrails = nodes.some((n) => n.data.nodeType === "guardrail");
  const hasMemory = nodes.some((n) => n.data.nodeType === "memory");
  const hasHandoff = nodes.some((n) => n.data.nodeType === "human_handoff");
  const hasRouter = nodes.some((n) => n.data.nodeType === "router");

  let step = 3;

  if (hasSystemPrompt) {
    lines.push(`${step}. For SystemPrompt nodes: configure the LLM with the given system message, model, and temperature`);
    step++;
  }

  if (hasTools) {
    lines.push(`${step}. For Tool nodes: implement each tool function (API calls with fetch, DB queries with Drizzle, custom functions)`);
    lines.push(`${step + 1}. Register tools with the agent so the LLM can call them via function calling`);
    step += 2;
  }

  if (hasGuardrails) {
    lines.push(`${step}. For Guardrail nodes: implement input/output filtering middleware that checks messages before/after LLM processing`);
    step++;
  }

  if (hasMemory) {
    const memoryNodes = nodes.filter((n) => n.data.nodeType === "memory");
    for (const mn of memoryNodes) {
      const mc = mn.data.config as MemoryConfig;
      if (mc.memory_type === "conversation") {
        lines.push(`${step}. Implement conversation history storage (max ${mc.capacity || 100} messages) with TTL`);
      } else if (mc.memory_type === "vector") {
        lines.push(`${step}. Implement vector store for semantic search (embedding model: ${mc.embedding_model || "text-embedding-3-small"})`);
      } else {
        lines.push(`${step}. Implement key-value memory store with TTL support`);
      }
      step++;
    }
  }

  if (hasRouter) {
    lines.push(`${step}. For Router nodes: implement intent classification or condition-based routing to direct messages to the correct sub-agent`);
    step++;
  }

  if (hasHandoff) {
    lines.push(`${step}. For HumanHandoff nodes: implement escalation logic (detect triggers, transfer context to human queue/email/webhook)`);
    step++;
  }

  lines.push(`${step}. Store the agent configuration in src/agents/config.ts`);
  lines.push(`${step + 1}. Ensure all tool calls are type-safe with proper error handling`);
  lines.push(`${step + 2}. Add a chat UI component that connects to the /api/agent/chat endpoint`);

  return lines.join("\n");
}
