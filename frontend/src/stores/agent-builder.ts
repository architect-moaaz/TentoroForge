import { create } from "zustand";
import type {
  AgentDefinition,
  AgentListItem,
  AgentTestMessage,
  AgentTemplate,
} from "@/types/agent-builder";

interface AgentBuilderState {
  agents: AgentListItem[];
  currentAgent: AgentDefinition | null;
  selectedNodeId: string | null;
  isLoading: boolean;
  error: string | null;

  // Test console state
  testMessages: AgentTestMessage[];
  isRunning: boolean;

  // Templates
  templates: AgentTemplate[];

  // Actions
  setAgents: (agents: AgentListItem[]) => void;
  setCurrentAgent: (agent: AgentDefinition | null) => void;
  setSelectedNodeId: (nodeId: string | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setTestMessages: (messages: AgentTestMessage[]) => void;
  addTestMessage: (message: AgentTestMessage) => void;
  setIsRunning: (running: boolean) => void;
  setTemplates: (templates: AgentTemplate[]) => void;
  reset: () => void;
}

export const useAgentBuilderStore = create<AgentBuilderState>((set) => ({
  agents: [],
  currentAgent: null,
  selectedNodeId: null,
  isLoading: false,
  error: null,
  testMessages: [],
  isRunning: false,
  templates: [],

  setAgents: (agents) => set({ agents, error: null }),
  setCurrentAgent: (agent) => set({ currentAgent: agent }),
  setSelectedNodeId: (nodeId) => set({ selectedNodeId: nodeId }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error, isLoading: false }),
  setTestMessages: (messages) => set({ testMessages: messages }),
  addTestMessage: (message) =>
    set((state) => ({ testMessages: [...state.testMessages, message] })),
  setIsRunning: (running) => set({ isRunning: running }),
  setTemplates: (templates) => set({ templates }),
  reset: () =>
    set({
      agents: [],
      currentAgent: null,
      selectedNodeId: null,
      isLoading: false,
      error: null,
      testMessages: [],
      isRunning: false,
      templates: [],
    }),
}));
