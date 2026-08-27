/** Decision graph (DRD) evaluator — topological sort and context propagation. */

import { evaluateDecisionTable } from "./table-evaluator";
import type {
  DecisionGraphDefinition,
  DecisionGraphResult,
  DecisionTableResult,
} from "@/types/decision";

/** Evaluate a decision graph by resolving decisions in topological order. */
export function evaluateDecisionGraph(
  graph: DecisionGraphDefinition,
  inputs: Record<string, unknown>,
): DecisionGraphResult {
  const order = topologicalSort(graph);
  const context = { ...inputs };
  const decisions: Record<string, DecisionTableResult> = {};

  for (const nodeId of order) {
    const node = graph.nodes.find((n) => n.id === nodeId);
    if (!node) continue;

    // Only evaluate decision nodes
    if (node.type !== "decision" || !node.decisionTableId) continue;

    const table = graph.tables[node.decisionTableId];
    if (!table) continue;

    const result = evaluateDecisionTable(table, context);
    decisions[nodeId] = result;

    // Propagate outputs into context for downstream decisions
    const output = Array.isArray(result.result)
      ? result.result[0] ?? {}
      : result.result;

    for (const [key, value] of Object.entries(output)) {
      context[`${node.label}.${key}`] = value;
      context[key] = value;
    }
  }

  // Collect final outputs from leaf decision nodes
  const leafNodeIds = findLeafNodes(graph);
  const finalOutputs: Record<string, unknown> = {};
  for (const nodeId of leafNodeIds) {
    const result = decisions[nodeId];
    if (result) {
      const output = Array.isArray(result.result)
        ? result.result
        : result.result;
      if (!Array.isArray(output)) {
        Object.assign(finalOutputs, output);
      }
    }
  }

  return { decisions, finalOutputs };
}

/** Topological sort using Kahn's algorithm. */
function topologicalSort(graph: DecisionGraphDefinition): string[] {
  const inDegree = new Map<string, number>();
  const adjacency = new Map<string, string[]>();

  for (const node of graph.nodes) {
    inDegree.set(node.id, 0);
    adjacency.set(node.id, []);
  }

  for (const edge of graph.edges) {
    const targets = adjacency.get(edge.source) ?? [];
    targets.push(edge.target);
    adjacency.set(edge.source, targets);
    inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
  }

  const queue: string[] = [];
  for (const [nodeId, degree] of inDegree) {
    if (degree === 0) queue.push(nodeId);
  }

  const sorted: string[] = [];
  while (queue.length > 0) {
    const nodeId = queue.shift()!;
    sorted.push(nodeId);

    for (const target of adjacency.get(nodeId) ?? []) {
      const newDegree = (inDegree.get(target) ?? 1) - 1;
      inDegree.set(target, newDegree);
      if (newDegree === 0) queue.push(target);
    }
  }

  return sorted;
}

/** Find leaf decision nodes (no outgoing information edges to other decisions). */
function findLeafNodes(graph: DecisionGraphDefinition): string[] {
  const hasOutgoing = new Set<string>();
  for (const edge of graph.edges) {
    if (edge.type === "information") {
      const targetNode = graph.nodes.find((n) => n.id === edge.target);
      if (targetNode?.type === "decision") {
        hasOutgoing.add(edge.source);
      }
    }
  }

  return graph.nodes
    .filter((n) => n.type === "decision" && !hasOutgoing.has(n.id))
    .map((n) => n.id);
}
