import { create } from "zustand";
import type { WorkflowDefinition, WorkflowListItem, WorkflowNodeData, ExecutionLog } from "@/types/workflow";
import type { Node, Edge } from "@xyflow/react";

interface WorkflowState {
  workflows: WorkflowListItem[];
  currentWorkflow: WorkflowDefinition | null;
  selectedNodeId: string | null;
  isLoading: boolean;
  error: string | null;

  // Execution/testing state
  executionLog: ExecutionLog | null;
  isExecuting: boolean;

  // Actions
  setWorkflows: (workflows: WorkflowListItem[]) => void;
  setCurrentWorkflow: (workflow: WorkflowDefinition | null) => void;
  setSelectedNodeId: (nodeId: string | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setExecutionLog: (log: ExecutionLog | null) => void;
  setIsExecuting: (executing: boolean) => void;
  reset: () => void;
}

export const useWorkflowStore = create<WorkflowState>((set) => ({
  workflows: [],
  currentWorkflow: null,
  selectedNodeId: null,
  isLoading: false,
  error: null,
  executionLog: null,
  isExecuting: false,

  setWorkflows: (workflows) => set({ workflows, error: null }),
  setCurrentWorkflow: (workflow) => set({ currentWorkflow: workflow }),
  setSelectedNodeId: (nodeId) => set({ selectedNodeId: nodeId }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error, isLoading: false }),
  setExecutionLog: (log) => set({ executionLog: log }),
  setIsExecuting: (executing) => set({ isExecuting: executing }),
  reset: () =>
    set({
      workflows: [],
      currentWorkflow: null,
      selectedNodeId: null,
      isLoading: false,
      error: null,
      executionLog: null,
      isExecuting: false,
    }),
}));
