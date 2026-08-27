"use client";

import { Bot, Search, Shield, MessageSquare, GitFork } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { AgentTemplate, AgentNodeSerialized, AgentEdgeSerialized } from "@/types/agent-builder";

const ICONS: Record<string, typeof Bot> = {
  Bot,
  Search,
  Shield,
  MessageSquare,
  GitFork,
};

const AGENT_TEMPLATES: AgentTemplate[] = [
  {
    id: "customer_support",
    name: "Customer Support Bot",
    description: "System prompt with knowledge base tool, guardrails, and human handoff",
    icon: "Bot",
    nodes: [
      {
        id: "sp_1",
        type: "system_prompt",
        position: { x: 50, y: 100 },
        data: {
          label: "Support Agent",
          nodeType: "system_prompt",
          config: {
            prompt: "You are a friendly customer support agent. Help users with their questions using the knowledge base. If you cannot resolve the issue, escalate to a human agent.",
            is_entry_point: true,
          },
        },
      },
      {
        id: "tool_1",
        type: "tool",
        position: { x: 300, y: 50 },
        data: {
          label: "Knowledge Base",
          nodeType: "tool",
          config: {
            tool_name: "search_knowledge_base",
            tool_type: "api_call",
            description: "Search the knowledge base for relevant articles",
          },
        },
      },
      {
        id: "guard_1",
        type: "guardrail",
        position: { x: 300, y: 180 },
        data: {
          label: "Output Filter",
          nodeType: "guardrail",
          config: {
            guardrail_type: "output_filter",
            rules: [
              { id: "r1", name: "No internal info", type: "content_policy" },
            ],
          },
        },
      },
      {
        id: "handoff_1",
        type: "human_handoff",
        position: { x: 550, y: 100 },
        data: {
          label: "Escalate to Human",
          nodeType: "human_handoff",
          config: {
            conditions: { explicit_request: true, keyword_triggers: ["human", "agent", "speak to someone"] },
            target: { type: "queue", value: "support-queue" },
          },
        },
      },
    ],
    edges: [
      { id: "e1", source: "sp_1", target: "tool_1", data: { edgeType: "default" } },
      { id: "e2", source: "sp_1", target: "guard_1", data: { edgeType: "default" } },
      { id: "e3", source: "guard_1", target: "handoff_1", data: { edgeType: "default" } },
    ],
  },
  {
    id: "data_assistant",
    name: "Data Assistant",
    description: "SQL tool with conversation memory and output guardrails",
    icon: "Search",
    nodes: [
      {
        id: "sp_1",
        type: "system_prompt",
        position: { x: 50, y: 100 },
        data: {
          label: "Data Analyst",
          nodeType: "system_prompt",
          config: {
            prompt: "You are a data analyst assistant. Help users query and analyze data. Write SQL queries when asked and explain results clearly.",
            is_entry_point: true,
          },
        },
      },
      {
        id: "tool_1",
        type: "tool",
        position: { x: 300, y: 50 },
        data: {
          label: "SQL Query",
          nodeType: "tool",
          config: {
            tool_name: "execute_sql",
            tool_type: "db_query",
            description: "Execute SQL queries against the database",
          },
        },
      },
      {
        id: "mem_1",
        type: "memory",
        position: { x: 300, y: 180 },
        data: {
          label: "Conversation Memory",
          nodeType: "memory",
          config: { memory_type: "conversation", capacity: 50 },
        },
      },
      {
        id: "guard_1",
        type: "guardrail",
        position: { x: 550, y: 100 },
        data: {
          label: "Output Guard",
          nodeType: "guardrail",
          config: {
            guardrail_type: "output_filter",
            rules: [
              { id: "r1", name: "No sensitive data", type: "pii_redaction" },
            ],
          },
        },
      },
    ],
    edges: [
      { id: "e1", source: "sp_1", target: "tool_1", data: { edgeType: "default" } },
      { id: "e2", source: "sp_1", target: "mem_1", data: { edgeType: "default" } },
      { id: "e3", source: "tool_1", target: "guard_1", data: { edgeType: "default" } },
    ],
  },
  {
    id: "content_moderator",
    name: "Content Moderator",
    description: "Input guardrail, router, and output guardrail pipeline",
    icon: "Shield",
    nodes: [
      {
        id: "guard_in",
        type: "guardrail",
        position: { x: 50, y: 100 },
        data: {
          label: "Input Filter",
          nodeType: "guardrail",
          config: {
            guardrail_type: "input_filter",
            rules: [
              { id: "r1", name: "Block harmful content", type: "content_policy" },
              { id: "r2", name: "PII detection", type: "pii_redaction" },
            ],
          },
        },
      },
      {
        id: "router_1",
        type: "router",
        position: { x: 300, y: 100 },
        data: {
          label: "Content Router",
          nodeType: "router",
          config: {
            strategy: "intent_classification",
            routes: [
              { id: "rt1", label: "Safe content" },
              { id: "rt2", label: "Flagged content" },
            ],
          },
        },
      },
      {
        id: "sp_1",
        type: "system_prompt",
        position: { x: 550, y: 50 },
        data: {
          label: "Moderator",
          nodeType: "system_prompt",
          config: {
            prompt: "Review and moderate content. Provide clear explanations for any content decisions.",
          },
        },
      },
      {
        id: "guard_out",
        type: "guardrail",
        position: { x: 550, y: 180 },
        data: {
          label: "Output Filter",
          nodeType: "guardrail",
          config: {
            guardrail_type: "output_filter",
            rules: [
              { id: "r1", name: "Clean output", type: "content_policy" },
            ],
          },
        },
      },
    ],
    edges: [
      { id: "e1", source: "guard_in", target: "router_1", data: { edgeType: "default" } },
      { id: "e2", source: "router_1", target: "sp_1", sourceHandle: "default", data: { edgeType: "route" } },
      { id: "e3", source: "sp_1", target: "guard_out", data: { edgeType: "default" } },
    ],
  },
  {
    id: "faq_bot",
    name: "FAQ Bot",
    description: "System prompt with vector memory search tool",
    icon: "MessageSquare",
    nodes: [
      {
        id: "sp_1",
        type: "system_prompt",
        position: { x: 50, y: 100 },
        data: {
          label: "FAQ Agent",
          nodeType: "system_prompt",
          config: {
            prompt: "You answer frequently asked questions using the knowledge base. Be concise and accurate. If unsure, say so.",
            is_entry_point: true,
          },
        },
      },
      {
        id: "mem_1",
        type: "memory",
        position: { x: 300, y: 50 },
        data: {
          label: "Vector Store",
          nodeType: "memory",
          config: { memory_type: "vector", capacity: 1000, similarity_threshold: 0.7 },
        },
      },
      {
        id: "tool_1",
        type: "tool",
        position: { x: 300, y: 180 },
        data: {
          label: "Search Tool",
          nodeType: "tool",
          config: {
            tool_name: "search_faqs",
            tool_type: "api_call",
            description: "Search the FAQ database",
          },
        },
      },
    ],
    edges: [
      { id: "e1", source: "sp_1", target: "mem_1", data: { edgeType: "default" } },
      { id: "e2", source: "sp_1", target: "tool_1", data: { edgeType: "default" } },
    ],
  },
  {
    id: "multi_agent_router",
    name: "Multi-Agent Router",
    description: "Router distributing to multiple specialized agents with tools",
    icon: "GitFork",
    nodes: [
      {
        id: "router_1",
        type: "router",
        position: { x: 50, y: 120 },
        data: {
          label: "Intent Router",
          nodeType: "router",
          config: {
            strategy: "intent_classification",
            routes: [
              { id: "rt1", label: "Billing" },
              { id: "rt2", label: "Technical" },
            ],
            default_route: "general",
          },
        },
      },
      {
        id: "sp_billing",
        type: "system_prompt",
        position: { x: 350, y: 30 },
        data: {
          label: "Billing Agent",
          nodeType: "system_prompt",
          config: { prompt: "You handle billing inquiries. Help with invoices, payments, and subscriptions." },
        },
      },
      {
        id: "sp_tech",
        type: "system_prompt",
        position: { x: 350, y: 150 },
        data: {
          label: "Tech Support",
          nodeType: "system_prompt",
          config: { prompt: "You handle technical support. Help with debugging, setup, and configuration." },
        },
      },
      {
        id: "sp_general",
        type: "system_prompt",
        position: { x: 350, y: 270 },
        data: {
          label: "General Agent",
          nodeType: "system_prompt",
          config: { prompt: "You handle general inquiries that don't fit billing or technical categories." },
        },
      },
      {
        id: "tool_billing",
        type: "tool",
        position: { x: 600, y: 30 },
        data: {
          label: "Billing API",
          nodeType: "tool",
          config: { tool_name: "billing_api", tool_type: "api_call" },
        },
      },
      {
        id: "tool_tech",
        type: "tool",
        position: { x: 600, y: 150 },
        data: {
          label: "Docs Search",
          nodeType: "tool",
          config: { tool_name: "search_docs", tool_type: "api_call" },
        },
      },
    ],
    edges: [
      { id: "e1", source: "router_1", target: "sp_billing", sourceHandle: "default", data: { edgeType: "route" } },
      { id: "e2", source: "router_1", target: "sp_tech", sourceHandle: "route_1", data: { edgeType: "route" } },
      { id: "e3", source: "router_1", target: "sp_general", sourceHandle: "route_2", data: { edgeType: "route" } },
      { id: "e4", source: "sp_billing", target: "tool_billing", data: { edgeType: "default" } },
      { id: "e5", source: "sp_tech", target: "tool_tech", data: { edgeType: "default" } },
    ],
  },
];

interface AgentTemplateSelectorProps {
  onSelect: (template: AgentTemplate) => void;
}

export function AgentTemplateSelector({ onSelect }: AgentTemplateSelectorProps) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-muted-foreground">Start from a template</p>
      <div className="grid gap-2">
        {AGENT_TEMPLATES.map((template) => {
          const Icon = ICONS[template.icon] || Bot;
          return (
            <Button
              key={template.id}
              variant="outline"
              className="h-auto justify-start p-3 text-left"
              onClick={() => onSelect(template)}
            >
              <Icon className="h-4 w-4 mr-2 shrink-0 text-muted-foreground" />
              <div className="min-w-0">
                <div className="text-xs font-medium">{template.name}</div>
                <div className="text-[10px] text-muted-foreground truncate">
                  {template.description}
                </div>
              </div>
            </Button>
          );
        })}
      </div>
    </div>
  );
}

export { AGENT_TEMPLATES };
