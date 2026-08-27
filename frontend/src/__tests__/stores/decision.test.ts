/**
 * Tests for the decision Zustand store.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useDecisionStore } from "@/stores/decision";
import type {
  DecisionTableDefinition,
  DecisionGraphDefinition,
  DRDNode,
  DRDEdge,
} from "@/types/decision";

const SAMPLE_TABLE: DecisionTableDefinition = {
  id: "dt1",
  name: "Test Table",
  hitPolicy: "F",
  inputs: [{ id: "i1", name: "age", label: "age", type: "number" }],
  outputs: [{ id: "o1", name: "category", label: "Category", type: "string" }],
  rules: [
    { id: "r1", inputEntries: ["< 18"], outputEntries: ["minor"] },
    { id: "r2", inputEntries: [">= 18"], outputEntries: ["adult"] },
  ],
};

const SAMPLE_GRAPH: DecisionGraphDefinition = {
  id: "dg1",
  name: "Test Graph",
  nodes: [
    { id: "n1", type: "inputData", label: "Age Input", position: { x: 0, y: 0 } },
  ],
  edges: [],
  tables: {},
};

describe("useDecisionStore", () => {
  beforeEach(() => {
    // Reset to initial state
    useDecisionStore.setState({
      activeTable: null,
      testCases: [],
      testResults: [],
      analysisResult: null,
      highlightedRuleIds: [],
      currentGraph: null,
      selectedDRDNodeId: null,
      versions: [],
      selectedVersionIndex: null,
      compareVersionIndex: null,
    });
  });

  // --- Active Table ---

  it("starts with null activeTable", () => {
    expect(useDecisionStore.getState().activeTable).toBeNull();
  });

  it("setActiveTable sets the table", () => {
    useDecisionStore.getState().setActiveTable(SAMPLE_TABLE);
    expect(useDecisionStore.getState().activeTable?.id).toBe("dt1");
  });

  it("setActiveTable can clear the table", () => {
    useDecisionStore.getState().setActiveTable(SAMPLE_TABLE);
    useDecisionStore.getState().setActiveTable(null);
    expect(useDecisionStore.getState().activeTable).toBeNull();
  });

  // --- Test Cases ---

  it("addTestCase appends a test case", () => {
    useDecisionStore.getState().addTestCase({
      id: "tc1",
      name: "Minor test",
      inputs: { age: 10 },
      expectedOutputs: { category: "minor" },
    });
    expect(useDecisionStore.getState().testCases).toHaveLength(1);
  });

  it("removeTestCase removes by id", () => {
    useDecisionStore.getState().addTestCase({
      id: "tc1",
      name: "Test 1",
      inputs: {},
      expectedOutputs: {},
    });
    useDecisionStore.getState().addTestCase({
      id: "tc2",
      name: "Test 2",
      inputs: {},
      expectedOutputs: {},
    });
    useDecisionStore.getState().removeTestCase("tc1");
    expect(useDecisionStore.getState().testCases).toHaveLength(1);
    expect(useDecisionStore.getState().testCases[0].id).toBe("tc2");
  });

  it("setTestCases replaces all test cases", () => {
    useDecisionStore.getState().addTestCase({
      id: "tc1",
      name: "Old",
      inputs: {},
      expectedOutputs: {},
    });
    useDecisionStore.getState().setTestCases([
      { id: "tc2", name: "New", inputs: {}, expectedOutputs: {} },
    ]);
    expect(useDecisionStore.getState().testCases).toHaveLength(1);
    expect(useDecisionStore.getState().testCases[0].id).toBe("tc2");
  });

  // --- Highlighted Rules ---

  it("setHighlightedRuleIds updates highlighted rules", () => {
    useDecisionStore.getState().setHighlightedRuleIds(["r1", "r2"]);
    expect(useDecisionStore.getState().highlightedRuleIds).toEqual(["r1", "r2"]);
  });

  // --- DRD Graph ---

  it("setCurrentGraph sets the graph", () => {
    useDecisionStore.getState().setCurrentGraph(SAMPLE_GRAPH);
    expect(useDecisionStore.getState().currentGraph?.id).toBe("dg1");
  });

  it("addDRDNode adds a node to the graph", () => {
    useDecisionStore.getState().setCurrentGraph(SAMPLE_GRAPH);
    const newNode: DRDNode = {
      id: "n2",
      type: "decision",
      label: "Decision 1",
      position: { x: 100, y: 100 },
    };
    useDecisionStore.getState().addDRDNode(newNode);
    expect(useDecisionStore.getState().currentGraph?.nodes).toHaveLength(2);
  });

  it("addDRDNode does nothing without a graph", () => {
    const newNode: DRDNode = {
      id: "n2",
      type: "decision",
      label: "Decision 1",
      position: { x: 0, y: 0 },
    };
    useDecisionStore.getState().addDRDNode(newNode);
    expect(useDecisionStore.getState().currentGraph).toBeNull();
  });

  it("updateDRDNode updates a node", () => {
    useDecisionStore.getState().setCurrentGraph(SAMPLE_GRAPH);
    useDecisionStore.getState().updateDRDNode("n1", { label: "Updated Label" });
    expect(useDecisionStore.getState().currentGraph?.nodes[0].label).toBe("Updated Label");
  });

  it("removeDRDNode removes node and its edges", () => {
    const graph: DecisionGraphDefinition = {
      ...SAMPLE_GRAPH,
      nodes: [
        { id: "n1", type: "inputData", label: "Input", position: { x: 0, y: 0 } },
        { id: "n2", type: "decision", label: "Decision", position: { x: 100, y: 0 } },
      ],
      edges: [{ id: "e1", source: "n1", target: "n2", type: "information" as const }],
    };
    useDecisionStore.getState().setCurrentGraph(graph);
    useDecisionStore.getState().removeDRDNode("n1");
    const state = useDecisionStore.getState();
    expect(state.currentGraph?.nodes).toHaveLength(1);
    expect(state.currentGraph?.edges).toHaveLength(0);
  });

  it("removeDRDNode clears selection if selected node removed", () => {
    useDecisionStore.getState().setCurrentGraph(SAMPLE_GRAPH);
    useDecisionStore.getState().setSelectedDRDNodeId("n1");
    useDecisionStore.getState().removeDRDNode("n1");
    expect(useDecisionStore.getState().selectedDRDNodeId).toBeNull();
  });

  it("addDRDEdge adds an edge", () => {
    const graph: DecisionGraphDefinition = {
      ...SAMPLE_GRAPH,
      nodes: [
        { id: "n1", type: "inputData", label: "Input", position: { x: 0, y: 0 } },
        { id: "n2", type: "decision", label: "Decision", position: { x: 100, y: 0 } },
      ],
    };
    useDecisionStore.getState().setCurrentGraph(graph);
    useDecisionStore.getState().addDRDEdge({ id: "e1", source: "n1", target: "n2", type: "information" as const });
    expect(useDecisionStore.getState().currentGraph?.edges).toHaveLength(1);
  });

  it("removeDRDEdge removes an edge", () => {
    const graph: DecisionGraphDefinition = {
      ...SAMPLE_GRAPH,
      edges: [{ id: "e1", source: "n1", target: "n2", type: "information" as const }],
    };
    useDecisionStore.getState().setCurrentGraph(graph);
    useDecisionStore.getState().removeDRDEdge("e1");
    expect(useDecisionStore.getState().currentGraph?.edges).toHaveLength(0);
  });

  // --- Version History ---

  it("saveVersion saves a copy of the active table", () => {
    useDecisionStore.getState().setActiveTable(SAMPLE_TABLE);
    useDecisionStore.getState().saveVersion("Initial");
    const versions = useDecisionStore.getState().versions;
    expect(versions).toHaveLength(1);
    expect(versions[0].label).toBe("Initial");
    expect(versions[0].table.id).toBe("dt1");
  });

  it("saveVersion auto-labels if no label given", () => {
    useDecisionStore.getState().setActiveTable(SAMPLE_TABLE);
    useDecisionStore.getState().saveVersion();
    expect(useDecisionStore.getState().versions[0].label).toBe("v1");
  });

  it("saveVersion does nothing without active table", () => {
    useDecisionStore.getState().saveVersion("test");
    expect(useDecisionStore.getState().versions).toHaveLength(0);
  });

  it("saveVersion creates deep copies", () => {
    useDecisionStore.getState().setActiveTable(SAMPLE_TABLE);
    useDecisionStore.getState().saveVersion();
    // Modify active table
    useDecisionStore.getState().setActiveTable({
      ...SAMPLE_TABLE,
      name: "Modified",
    });
    // Version should still have original name
    expect(useDecisionStore.getState().versions[0].table.name).toBe("Test Table");
  });

  it("clearVersions clears all version state", () => {
    useDecisionStore.getState().setActiveTable(SAMPLE_TABLE);
    useDecisionStore.getState().saveVersion();
    useDecisionStore.getState().setSelectedVersionIndex(0);
    useDecisionStore.getState().setCompareVersionIndex(0);
    useDecisionStore.getState().clearVersions();
    const state = useDecisionStore.getState();
    expect(state.versions).toHaveLength(0);
    expect(state.selectedVersionIndex).toBeNull();
    expect(state.compareVersionIndex).toBeNull();
  });

  it("setSelectedVersionIndex and setCompareVersionIndex work", () => {
    useDecisionStore.getState().setSelectedVersionIndex(2);
    expect(useDecisionStore.getState().selectedVersionIndex).toBe(2);
    useDecisionStore.getState().setCompareVersionIndex(1);
    expect(useDecisionStore.getState().compareVersionIndex).toBe(1);
  });
});
