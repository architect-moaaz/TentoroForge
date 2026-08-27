/** Workflow runtime engine — orchestrates workflow execution. */

import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

import { StateManager } from '../infrastructure/state-manager';
import { ExecutionLogger } from '../infrastructure/execution-logger';
import { GatewayController } from '../domain/gateway-controller';
import { TaskExecutor } from './task-executor';
import { getAiHandler } from '../ai';
import type {
  WorkflowDefinition,
  WorkflowNode,
  WorkflowEdge,
} from '../domain/types';

export class WorkflowEngine {
  private state = new StateManager();
  private gateway = new GatewayController();
  private executor = new TaskExecutor(this.state);
  private execLogger = new ExecutionLogger();

  /** Start a new workflow instance from a workflow definition. */
  async startWorkflow(
    workflowId: string,
    variables?: Record<string, unknown>,
    initiatedBy?: string,
  ) {
    const definition = this.loadDefinition(workflowId);
    if (!definition) {
      throw new Error(`Workflow definition '${workflowId}' not found`);
    }

    const { nodes, edges } = definition.definition;
    if (!nodes.length) {
      throw new Error(`Workflow '${workflowId}' has no nodes`);
    }

    const instance = await this.state.createInstance({
      workflowId,
      workflowName: definition.name,
      initiatedBy: initiatedBy ?? null,
      variables: variables ?? {},
    });

    await this.state.transitionInstance(instance.id, 'running');

    const startNodes = this.findStartNodes(nodes, edges);
    if (!startNodes.length) {
      await this.state.transitionInstance(instance.id, 'failed', 'No start node found');
      return instance;
    }

    await this.executeNodes({
      instanceId: instance.id,
      nodeIds: startNodes.map((n) => n.id),
      nodes,
      edges,
    });

    // Re-fetch to get latest state
    return (await this.state.getInstance(instance.id)) ?? instance;
  }

  /** Complete a user task and advance the workflow. */
  async completeTask(taskId: string, outputData?: Record<string, unknown>) {
    const task = await this.state.getTask(taskId);
    if (!task) throw new Error(`Task ${taskId} not found`);

    const completableStatuses = ['pending', 'assigned', 'active'];
    if (!completableStatuses.includes(task.status)) {
      throw new Error(`Task ${taskId} is not in a completable state (status=${task.status})`);
    }

    await this.state.completeTask(taskId, outputData);

    const instance = await this.state.getInstance(task.workflowInstanceId);
    if (!instance) throw new Error(`Workflow instance for task ${taskId} not found`);

    // Merge output data into workflow variables
    if (outputData) {
      for (const [key, value] of Object.entries(outputData)) {
        await this.state.setVariable(instance.id, key, value);
      }
    }

    // Set previous variable
    await this.state.setVariable(instance.id, 'previous', {
      node_id: task.nodeId,
      output: outputData,
    });

    // Load definition and advance
    const definition = this.loadDefinition(instance.workflowId);
    if (definition) {
      const { nodes, edges } = definition.definition;
      const nextNodeIds = edges
        .filter((e) => e.source === task.nodeId)
        .map((e) => e.target);

      if (nextNodeIds.length > 0) {
        await this.executeNodes({
          instanceId: instance.id,
          nodeIds: nextNodeIds,
          nodes,
          edges,
        });
      } else {
        // Check completion
        const pending = await this.state.listPendingTasksForInstance(instance.id);
        if (pending.length === 0) {
          await this.state.transitionInstance(instance.id, 'completed');
        }
      }
    }

    return (await this.state.getTask(taskId)) ?? task;
  }

  /** Cancel a running workflow instance. */
  async cancelWorkflow(instanceId: string) {
    const instance = await this.state.getInstance(instanceId);
    if (!instance) throw new Error(`Workflow instance ${instanceId} not found`);

    if (instance.status === 'completed' || instance.status === 'cancelled') {
      throw new Error(`Workflow is already ${instance.status}`);
    }

    await this.state.cancelPendingTasks(instanceId);
    await this.state.transitionInstance(instanceId, 'cancelled');

    return (await this.state.getInstance(instanceId)) ?? instance;
  }

  // --- Internal execution logic (exposed for timer-scheduler) ---

  /** Execute a set of nodes, handling gateways and task creation. */
  async executeNodes(params: {
    instanceId: string;
    nodeIds: string[];
    nodes: WorkflowNode[];
    edges: WorkflowEdge[];
  }): Promise<void> {
    const { instanceId, nodes, edges } = params;
    const nodeMap = new Map(nodes.map((n) => [n.id, n]));
    const completedInThisPass = new Set<string>();
    const toProcess = [...params.nodeIds];

    // Termination guard.
    //
    // This queue walk had NO step budget and NO visited set, so a loop-back
    // edge re-queued forever. Because this engine runs inside a route
    // handler, that hangs the REQUEST rather than crashing the process —
    // the user's browser spins, the connection is held, and nothing in the
    // logs says why. Engine #1 has `_MAX_STEPS` (see engine.ts, where the
    // budget is now a shared cell plus a depth guard); this engine had
    // nothing at all.
    //
    // The budget is generous: it bounds `nodes × revisits`, and a legitimate
    // pass never approaches it.
    const MAX_STEPS = 5000;
    let steps = 0;

    while (toProcess.length > 0) {
      if (++steps > MAX_STEPS) {
        throw new Error(
          `[workflow-engine] instance ${instanceId} exceeded ${MAX_STEPS} node ` +
          `executions — almost certainly a loop-back edge. Aborting so the ` +
          `request fails instead of hanging. Queue head: ${toProcess.slice(0, 5).join(", ")}`,
        );
      }
      const currentId = toProcess.shift()!;
      const node = nodeMap.get(currentId);
      if (!node) {
        console.warn(`[workflow] Node ${currentId} not found in definition`);
        continue;
      }

      const nodeType = node.type ?? 'action';
      const nodeLabel = node.data?.label ?? currentId;
      const config = node.data?.config ?? {};
      const variables = await this.state.getVariables(instanceId);

      // Log start
      const logEntry = await this.execLogger.logStart({
        instanceId,
        nodeId: currentId,
        nodeType,
        nodeLabel,
        inputSnapshot: { variables_keys: Object.keys(variables), config },
      });

      try {
        // Handle trigger nodes — seed trigger variables
        if (nodeType === 'trigger') {
          await this.state.setVariable(instanceId, 'trigger', { ...variables });
          await this.state.setVariable(instanceId, 'previous', {
            node_id: currentId,
            output: { ...variables },
          });
          completedInThisPass.add(currentId);
          await this.execLogger.logComplete(logEntry.id, { trigger_seeded: true });
          const nextIds = this.getNextNodeIds(currentId, edges);
          toProcess.push(...nextIds);
          continue;
        }

        // Handle end nodes
        if (nodeType === 'end' || nodeType === 'end_event') {
          completedInThisPass.add(currentId);
          await this.execLogger.logComplete(logEntry.id, { ended: true });
          continue;
        }

        // Handle condition nodes
        if (nodeType === 'condition') {
          const nextIds = this.gateway.resolveConditionNode(node, edges, variables);
          completedInThisPass.add(currentId);
          await this.execLogger.logComplete(logEntry.id, { branch_targets: nextIds });
          toProcess.push(...nextIds);
          continue;
        }

        // Handle exclusive gateway
        if (nodeType === 'exclusive_gateway') {
          const nextIds = this.gateway.resolveExclusiveGateway(node, edges, variables);
          completedInThisPass.add(currentId);
          await this.execLogger.logComplete(logEntry.id, { branch_targets: nextIds });
          toProcess.push(...nextIds);
          continue;
        }

        // Handle AI decide nodes
        if (nodeType === 'ai_decide') {
          const handler = getAiHandler('ai_decide', variables);
          const aiOutput = await handler.execute(config as Record<string, unknown>);
          const decision = Boolean(aiOutput.decision ?? true);

          await this.state.setVariable(instanceId, currentId, aiOutput);
          await this.state.setVariable(instanceId, 'previous', {
            node_id: currentId,
            output: aiOutput,
          });

          const nextIds = this.gateway.resolveAiDecideNode(node, edges, decision);
          completedInThisPass.add(currentId);
          await this.execLogger.logComplete(logEntry.id, aiOutput);
          toProcess.push(...nextIds);
          continue;
        }

        // Handle parallel gateway / fork / join
        if (['parallel_gateway', 'fork', 'join'].includes(nodeType)) {
          const incoming = edges.filter((e) => e.target === currentId);
          if (incoming.length > 1) {
            if (!this.gateway.checkJoinCondition(currentId, edges, completedInThisPass)) {
              await this.execLogger.logSkip({
                instanceId,
                nodeId: currentId,
                nodeType,
                nodeLabel,
                reason: 'Waiting for parallel paths to complete',
              });
              continue;
            }
          }

          const nextIds = this.gateway.resolveParallelGateway(node, edges, variables);
          completedInThisPass.add(currentId);
          await this.execLogger.logComplete(logEntry.id, { parallel_targets: nextIds });
          toProcess.push(...nextIds);
          continue;
        }

        // Handle event gateway
        if (nodeType === 'event_gateway') {
          const nextIds = this.gateway.resolveEventGateway(node, edges, variables);
          completedInThisPass.add(currentId);
          await this.execLogger.logComplete(logEntry.id, { event_targets: nextIds });
          toProcess.push(...nextIds);
          continue;
        }

        // Handle task nodes (user_task, service_task, action, ai_*, etc.)
        const task = await this.executor.executeNode({
          instanceId,
          node,
          variables,
        });

        const taskType = this.executor.classifyTaskType(nodeType);

        if (this.executor.isBlockingTask(taskType)) {
          await this.state.transitionInstance(instanceId, 'waiting');
          // Track which nodes we're waiting at
          const inst = await this.state.getInstance(instanceId);
          const current = [...((inst?.currentNodeIds as string[]) ?? [])];
          if (!current.includes(currentId)) current.push(currentId);
          await this.state.updateCurrentNodes(instanceId, current);

          await this.execLogger.logComplete(logEntry.id, {
            task_id: task.id,
            task_type: taskType,
            blocking: true,
          });
        } else {
          // Non-blocking service task already completed
          const completedTask = await this.state.getTask(task.id);
          const outputData = (completedTask?.outputData ?? {}) as Record<string, unknown>;
          if (outputData && Object.keys(outputData).length > 0) {
            await this.state.setVariable(instanceId, currentId, outputData);
            await this.state.setVariable(instanceId, 'previous', {
              node_id: currentId,
              output: outputData,
            });
          }

          completedInThisPass.add(currentId);
          await this.execLogger.logComplete(logEntry.id, {
            task_id: task.id,
            task_type: taskType,
            output: outputData,
          });
          const nextIds = this.getNextNodeIds(currentId, edges);
          toProcess.push(...nextIds);
        }
      } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        await this.execLogger.logFailure(logEntry.id, msg);
        console.error(`[workflow] Error executing node ${currentId}: ${msg}`);
        continue;
      }
    }

    // Check if workflow has reached all end nodes
    const pending = await this.state.listPendingTasksForInstance(instanceId);
    if (pending.length === 0 && completedInThisPass.size > 0) {
      for (const nid of completedInThisPass) {
        const n = nodeMap.get(nid);
        if (n && (n.type === 'end' || n.type === 'end_event')) {
          await this.state.transitionInstance(instanceId, 'completed');
          return;
        }
      }
    }
  }

  /** Load a workflow definition from the workflows/ directory. */
  loadDefinition(workflowId: string): WorkflowDefinition | null {
    const wfFile = join(process.cwd(), 'workflows', `${workflowId}.json`);
    if (!existsSync(wfFile)) return null;
    try {
      return JSON.parse(readFileSync(wfFile, 'utf-8')) as WorkflowDefinition;
    } catch {
      return null;
    }
  }

  private findStartNodes(nodes: WorkflowNode[], edges: WorkflowEdge[]): WorkflowNode[] {
    const targetIds = new Set(edges.map((e) => e.target));
    const startNodes: WorkflowNode[] = [];
    for (const node of nodes) {
      if (['start', 'start_event', 'trigger'].includes(node.type)) {
        startNodes.push(node);
      } else if (!targetIds.has(node.id)) {
        startNodes.push(node);
      }
    }
    return startNodes.length > 0 ? startNodes : nodes.slice(0, 1);
  }

  private getNextNodeIds(nodeId: string, edges: WorkflowEdge[]): string[] {
    return edges.filter((e) => e.source === nodeId).map((e) => e.target);
  }
}
