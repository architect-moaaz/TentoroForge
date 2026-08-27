/** Gateway controller — handles condition nodes, exclusive/parallel/event gateways, and AI-decide branching. */

import { VariableResolver } from './variable-resolver';
import { evaluateExpression } from './feel-lite';
import { evaluateDecisionTable, type DecisionTableDefinition } from './decision-evaluator';
import type { WorkflowNode, WorkflowEdge } from './types';

export class GatewayController {
  /** Resolve a condition node using node.data.config.expression + edgeType then/else. */
  resolveConditionNode(
    node: WorkflowNode,
    edges: WorkflowEdge[],
    variables: Record<string, unknown>,
  ): string[] {
    const config = node.data?.config ?? {};
    const expression = (config.expression as string) ?? '';

    const resolver = new VariableResolver(variables);
    const resolvedExpr = resolver.resolveString(expression);

    const result = this.evaluateCondition(resolvedExpr, variables);
    const edgeType = result ? 'then' : 'else';

    const outgoing = this.outgoingEdges(node.id, edges);
    const targets: string[] = [];
    const defaultTargets: string[] = [];

    for (const edge of outgoing) {
      const eType = edge.data?.edgeType ?? 'default';
      if (eType === edgeType) {
        targets.push(edge.target);
      } else if (eType === 'default') {
        defaultTargets.push(edge.target);
      }
    }

    if (targets.length > 0) return targets;
    if (defaultTargets.length > 0) return defaultTargets;
    return [];
  }

  /** Resolve a decision node — evaluate decision table and route via then/else. */
  resolveDecisionNode(
    node: WorkflowNode,
    edges: WorkflowEdge[],
    variables: Record<string, unknown>,
  ): { targets: string[]; result: Record<string, unknown> | Record<string, unknown>[] } {
    const config = node.data?.config ?? {};
    const tableDef = config.decisionTable as DecisionTableDefinition | undefined;

    if (!tableDef) {
      return { targets: this.outgoingEdges(node.id, edges).map(e => e.target), result: {} };
    }

    const evalResult = evaluateDecisionTable(tableDef, variables);
    const matched = evalResult.matchedRuleIds.length > 0;
    const edgeType = matched ? 'then' : 'else';

    const outgoing = this.outgoingEdges(node.id, edges);
    const targets: string[] = [];
    const defaultTargets: string[] = [];

    for (const edge of outgoing) {
      const eType = edge.data?.edgeType ?? 'default';
      if (eType === edgeType) targets.push(edge.target);
      else if (eType === 'default') defaultTargets.push(edge.target);
    }

    const finalTargets = targets.length > 0 ? targets : defaultTargets;
    return { targets: finalTargets, result: evalResult.result };
  }

  /** Route based on AI decision boolean — same then/else edge routing. */
  resolveAiDecideNode(
    node: WorkflowNode,
    edges: WorkflowEdge[],
    aiResult: boolean,
  ): string[] {
    const edgeType = aiResult ? 'then' : 'else';
    const outgoing = this.outgoingEdges(node.id, edges);
    const targets: string[] = [];
    const defaultTargets: string[] = [];

    for (const edge of outgoing) {
      const eType = edge.data?.edgeType ?? 'default';
      if (eType === edgeType) {
        targets.push(edge.target);
      } else if (eType === 'default') {
        defaultTargets.push(edge.target);
      }
    }

    if (targets.length > 0) return targets;
    if (defaultTargets.length > 0) return defaultTargets;
    return [];
  }

  /** XOR gateway — pick the first edge whose condition evaluates to True, or the default edge. */
  resolveExclusiveGateway(
    node: WorkflowNode,
    edges: WorkflowEdge[],
    variables: Record<string, unknown>,
  ): string[] {
    const outgoing = this.outgoingEdges(node.id, edges);
    const defaultTargets: string[] = [];

    for (const edge of outgoing) {
      const condition = edge.data?.condition;
      if (!condition) {
        defaultTargets.push(edge.target);
        continue;
      }
      if (this.evaluateCondition(condition, variables)) {
        return [edge.target];
      }
    }

    if (defaultTargets.length > 0) return [defaultTargets[0]];
    return [];
  }

  /** AND gateway — activate ALL outgoing edges simultaneously. */
  resolveParallelGateway(
    node: WorkflowNode,
    edges: WorkflowEdge[],
    _variables: Record<string, unknown>,
  ): string[] {
    const outgoing = this.outgoingEdges(node.id, edges);
    return outgoing.map((e) => e.target);
  }

  /** Event-based gateway — treat like exclusive gateway for now. */
  resolveEventGateway(
    node: WorkflowNode,
    edges: WorkflowEdge[],
    variables: Record<string, unknown>,
  ): string[] {
    return this.resolveExclusiveGateway(node, edges, variables);
  }

  /** Check if all incoming paths to a parallel join have completed. */
  checkJoinCondition(
    joinNodeId: string,
    edges: WorkflowEdge[],
    completedNodeIds: Set<string>,
  ): boolean {
    const incoming = this.incomingEdges(joinNodeId, edges);
    const sources = new Set(incoming.map((e) => e.source));
    for (const src of sources) {
      if (!completedNodeIds.has(src)) return false;
    }
    return true;
  }

  // --- Internal helpers ---

  private outgoingEdges(nodeId: string, edges: WorkflowEdge[]): WorkflowEdge[] {
    return edges.filter((e) => e.source === nodeId);
  }

  private incomingEdges(nodeId: string, edges: WorkflowEdge[]): WorkflowEdge[] {
    return edges.filter((e) => e.target === nodeId);
  }

  /** Safely evaluate a condition expression. Tries FEEL-lite first, falls back to string-split. */
  private evaluateCondition(condition: string, variables: Record<string, unknown>): boolean {
    try {
      condition = condition.trim();
      if (!condition) return false;

      // Try FEEL-lite parser first
      try {
        const result = evaluateExpression(condition, variables);
        return Boolean(result);
      } catch {
        // Fall back to legacy string-split evaluation
      }

      const operators = ['==', '!=', '>=', '<=', '>', '<'] as const;
      for (const op of operators) {
        if (condition.includes(op)) {
          const parts = condition.split(op);
          if (parts.length >= 2) {
            const leftRaw = parts[0].trim();
            const rightRaw = parts.slice(1).join(op).trim();

            let left = this.coerceValue(leftRaw);
            const right = this.coerceValue(rightRaw);

            // If left side looks like a variable name, try looking it up
            if (typeof left === 'string' && left === leftRaw && left in variables) {
              left = variables[left];
            }

            switch (op) {
              case '==': return left === right;
              case '!=': return left !== right;
              case '>': return Number(left) > Number(right);
              case '<': return Number(left) < Number(right);
              case '>=': return Number(left) >= Number(right);
              case '<=': return Number(left) <= Number(right);
            }
          }
        }
      }

      // Truthy check on variable
      const varVal = variables[condition];
      return varVal !== undefined ? Boolean(varVal) : Boolean(this.coerceValue(condition));
    } catch {
      return false;
    }
  }

  /** Coerce a string value to appropriate JS type. */
  private coerceValue(raw: string): unknown {
    raw = raw.trim().replace(/^['"]|['"]$/g, '');
    if (raw.toLowerCase() === 'true') return true;
    if (raw.toLowerCase() === 'false') return false;
    if (raw.toLowerCase() === 'null' || raw.toLowerCase() === 'none') return null;
    const asInt = parseInt(raw, 10);
    if (!isNaN(asInt) && String(asInt) === raw) return asInt;
    const asFloat = parseFloat(raw);
    if (!isNaN(asFloat)) return asFloat;
    return raw;
  }
}
