/** Decision table Zustand store. */

import { create } from "zustand";
import type {
  DecisionTableDefinition,
  DecisionTestCase,
  DecisionTestResult,
  DecisionAnalysisResult,
  DecisionGraphDefinition,
  DRDNode,
  DRDEdge,
} from "@/types/decision";

export interface DecisionVersion {
  table: DecisionTableDefinition;
  timestamp: number;
  label: string;
}

interface DecisionState {
  activeTable: DecisionTableDefinition | null;
  testCases: DecisionTestCase[];
  testResults: DecisionTestResult[];
  analysisResult: DecisionAnalysisResult | null;
  highlightedRuleIds: string[];

  // DRD state
  currentGraph: DecisionGraphDefinition | null;
  selectedDRDNodeId: string | null;

  // Version history
  versions: DecisionVersion[];
  selectedVersionIndex: number | null;
  compareVersionIndex: number | null;

  setActiveTable: (table: DecisionTableDefinition | null) => void;
  setTestCases: (cases: DecisionTestCase[]) => void;
  addTestCase: (tc: DecisionTestCase) => void;
  removeTestCase: (id: string) => void;
  setTestResults: (results: DecisionTestResult[]) => void;
  setAnalysisResult: (result: DecisionAnalysisResult | null) => void;
  setHighlightedRuleIds: (ids: string[]) => void;

  // DRD actions
  setCurrentGraph: (graph: DecisionGraphDefinition | null) => void;
  setSelectedDRDNodeId: (id: string | null) => void;
  addDRDNode: (node: DRDNode) => void;
  updateDRDNode: (id: string, updates: Partial<DRDNode>) => void;
  removeDRDNode: (id: string) => void;
  addDRDEdge: (edge: DRDEdge) => void;
  removeDRDEdge: (id: string) => void;
  updateDRDNodes: (nodes: DRDNode[]) => void;
  upsertDecisionTable: (table: DecisionTableDefinition) => void;

  // Version actions
  saveVersion: (label?: string) => void;
  setSelectedVersionIndex: (index: number | null) => void;
  setCompareVersionIndex: (index: number | null) => void;
  clearVersions: () => void;
}

export const useDecisionStore = create<DecisionState>((set) => ({
  activeTable: null,
  testCases: [],
  testResults: [],
  analysisResult: null,
  highlightedRuleIds: [],

  // DRD state
  currentGraph: null,
  selectedDRDNodeId: null,

  // Version history
  versions: [],
  selectedVersionIndex: null,
  compareVersionIndex: null,

  setActiveTable: (table) => set({ activeTable: table }),
  setTestCases: (cases) => set({ testCases: cases }),
  addTestCase: (tc) =>
    set((state) => ({ testCases: [...state.testCases, tc] })),
  removeTestCase: (id) =>
    set((state) => ({
      testCases: state.testCases.filter((tc) => tc.id !== id),
    })),
  setTestResults: (results) => set({ testResults: results }),
  setAnalysisResult: (result) => set({ analysisResult: result }),
  setHighlightedRuleIds: (ids) => set({ highlightedRuleIds: ids }),

  // DRD actions
  setCurrentGraph: (graph) => set({ currentGraph: graph }),
  setSelectedDRDNodeId: (id) => set({ selectedDRDNodeId: id }),

  addDRDNode: (node) =>
    set((state) => {
      if (!state.currentGraph) return state;
      return {
        currentGraph: {
          ...state.currentGraph,
          nodes: [...state.currentGraph.nodes, node],
        },
      };
    }),

  updateDRDNode: (id, updates) =>
    set((state) => {
      if (!state.currentGraph) return state;
      return {
        currentGraph: {
          ...state.currentGraph,
          nodes: state.currentGraph.nodes.map((n) =>
            n.id === id ? { ...n, ...updates } : n,
          ),
        },
      };
    }),

  removeDRDNode: (id) =>
    set((state) => {
      if (!state.currentGraph) return state;
      return {
        currentGraph: {
          ...state.currentGraph,
          nodes: state.currentGraph.nodes.filter((n) => n.id !== id),
          edges: state.currentGraph.edges.filter(
            (e) => e.source !== id && e.target !== id,
          ),
        },
        selectedDRDNodeId:
          state.selectedDRDNodeId === id ? null : state.selectedDRDNodeId,
      };
    }),

  addDRDEdge: (edge) =>
    set((state) => {
      if (!state.currentGraph) return state;
      return {
        currentGraph: {
          ...state.currentGraph,
          edges: [...state.currentGraph.edges, edge],
        },
      };
    }),

  removeDRDEdge: (id) =>
    set((state) => {
      if (!state.currentGraph) return state;
      return {
        currentGraph: {
          ...state.currentGraph,
          edges: state.currentGraph.edges.filter((e) => e.id !== id),
        },
      };
    }),

  updateDRDNodes: (nodes) =>
    set((state) => {
      if (!state.currentGraph) return state;
      return {
        currentGraph: { ...state.currentGraph, nodes },
      };
    }),

  upsertDecisionTable: (table) =>
    set((state) => {
      if (!state.currentGraph) return state;
      return {
        currentGraph: {
          ...state.currentGraph,
          tables: { ...state.currentGraph.tables, [table.id]: table },
        },
      };
    }),

  // Version actions
  saveVersion: (label) =>
    set((state) => {
      if (!state.activeTable) return state;
      const version: DecisionVersion = {
        table: JSON.parse(JSON.stringify(state.activeTable)),
        timestamp: Date.now(),
        label: label || `v${state.versions.length + 1}`,
      };
      return { versions: [...state.versions, version] };
    }),

  setSelectedVersionIndex: (index) => set({ selectedVersionIndex: index }),
  setCompareVersionIndex: (index) => set({ compareVersionIndex: index }),
  clearVersions: () =>
    set({ versions: [], selectedVersionIndex: null, compareVersionIndex: null }),
}));
