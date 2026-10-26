"use client";

/**
 * What the workflow editor needs to know about assistants: the project's list (for the picker and for the name on the
 * canvas badge) and one assistant's tools (for the "it may change" picker).
 *
 * The list uses the SAME query key the Agents tab uses, so the two stay in step: an assistant made for a step shows up
 * in the Agents tab without a reload, and one deleted there leaves the picker.
 */
import { createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { assistantTools, type AssistantTool } from "@/lib/agent-step";
import type { AgentListItem } from "@/types/agent-builder";

export const assistantsKey = (projectId: string) => ["project", projectId, "agent-definitions"] as const;

/** The project's assistants (id, name, description, node_count). Empty while loading or when there is no project. */
export function useAssistants(projectId: string | undefined, enabled = true) {
  const q = useQuery({
    queryKey: assistantsKey(projectId ?? ""),
    queryFn: () => api.get<AgentListItem[]>(`/api/projects/${projectId}/agent-definitions`),
    enabled: !!projectId && enabled,
  });
  return {
    assistants: Array.isArray(q.data) ? q.data : [],
    loading: q.isLoading,
    failed: q.isError,
  };
}

/**
 * One assistant's tools, read from its definition. `tools` stays null when they cannot be read (no assistant yet,
 * an older platform, a network error): the panel then asks for the names as plain text instead.
 */
export function useAssistantTools(projectId: string | undefined, agentId: string | undefined) {
  const q = useQuery({
    queryKey: [...assistantsKey(projectId ?? ""), agentId ?? "", "tools"],
    queryFn: async (): Promise<AssistantTool[]> => {
      const def = await api.get<{ nodes?: unknown }>(`/api/projects/${projectId}/agent-definitions/${agentId}`);
      return assistantTools(def);
    },
    enabled: !!projectId && !!agentId,
    retry: false,
  });
  return {
    tools: q.data ?? null,
    loading: !!agentId && q.isLoading,
    failed: q.isError,
  };
}

/** id -> name for the assistants the canvas badge can name. Provided by the workflow panel. */
export const AssistantNamesContext = createContext<Record<string, string>>({});

export function useAssistantName(agentId: string | undefined): string | undefined {
  const names = useContext(AssistantNamesContext);
  return agentId ? names[agentId] : undefined;
}
