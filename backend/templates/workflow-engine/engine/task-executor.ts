/** Task executor — executes different task types within a workflow. */

import { StateManager } from '../infrastructure/state-manager';
import { getDispatcher } from '../actions';
import { getAiHandler } from '../ai';
import { parseDuration } from './timer-scheduler';
import type { TaskType } from '../domain/types';
import type { WfTaskInstance } from '../infrastructure/schema';

export class TaskExecutor {
  constructor(private state: StateManager) {}

  /** Execute a workflow node — creates a TaskInstance and processes it. */
  async executeNode(params: {
    instanceId: string;
    node: { id: string; type?: string; data?: { label?: string; config?: Record<string, unknown> } };
    variables: Record<string, unknown>;
  }): Promise<WfTaskInstance> {
    const { instanceId, node, variables } = params;
    const nodeId = node.id;
    const nodeType = node.type ?? 'action';
    const nodeLabel = node.data?.label ?? nodeId;
    const config = node.data?.config ?? {};

    const taskType = this.classifyTaskType(nodeType);

    // Resolve assignment for user tasks
    let assigneeId: string | null = null;
    let assigneeType: string | null = null;
    if (taskType === 'user_task') {
      const assignType = config.assignType as string | undefined;

      if (nodeType === 'task_pool') {
        assigneeType = 'pool';
      } else if (nodeType === 'escalation') {
        assigneeType = 'escalation';
      } else if (assignType === 'initiator') {
        // Assign directly to the workflow initiator
        const instance = await this.state.getInstance(instanceId);
        if (instance?.initiatedBy) {
          assigneeId = instance.initiatedBy;
        }
        assigneeType = 'initiator';
      } else if (assignType === 'process_variable') {
        // Resolve variable path to a concrete person ID
        const variablePath = config.assignVariablePath as string | undefined;
        if (variablePath) {
          const { VariableResolver } = await import('../domain/variable-resolver');
          const resolver = new VariableResolver(variables);
          const resolved = resolver.resolveString(variablePath);
          if (resolved && resolved !== variablePath) {
            assigneeId = resolved;
          }
        }
        assigneeType = 'process_variable';
      }
      // Generated apps handle remaining assignment types at the API level
    }

    // Calculate due date from SLA
    let dueAt: Date | null = null;
    const slaHours = config.slaHours as number | undefined;
    if (slaHours) {
      dueAt = new Date(Date.now() + slaHours * 3600_000);
    }

    const inputData: Record<string, unknown> = { variables, config };

    // For timer events, compute resumeAt
    if (taskType === 'timer_event') {
      const durationStr = (config.duration as string) ?? '1 hour';
      const durationMs = parseDuration(durationStr);
      const resumeAt = new Date(Date.now() + durationMs);
      inputData.resume_at = resumeAt.toISOString();
    }

    // For escalation nodes, store escalation metadata
    if (nodeType === 'escalation') {
      if (config.escalateTo) inputData.escalate_to = config.escalateTo;
      if (config.slaHours) inputData.sla_hours = config.slaHours;
    }

    const task = await this.state.createTask({
      workflowInstanceId: instanceId,
      nodeId,
      nodeLabel,
      taskType,
      assigneeId,
      assigneeType,
      inputData,
      dueAt,
    });

    console.log(
      `[workflow] Created task ${task.id} (type=${taskType}) for node ${nodeId} [${nodeType}]`,
    );

    // Auto-execute service tasks immediately
    if (taskType === 'service_task') {
      await this.executeServiceTask(task.id, nodeType, config, variables);
    }

    // Re-fetch to get updated output_data after execution
    return (await this.state.getTask(task.id)) ?? task;
  }

  private async executeServiceTask(
    taskId: string,
    nodeType: string,
    config: Record<string, unknown>,
    variables: Record<string, unknown>,
  ): Promise<void> {
    try {
      if (nodeType.startsWith('ai_')) {
        await this.executeAiTask(taskId, nodeType, config, variables);
        return;
      }

      const actionType = (config.actionType as string) ?? 'custom';
      console.log(`[workflow] Auto-executing service task ${taskId}: ${actionType}`);

      const dispatcher = getDispatcher(actionType, variables);
      const output = await dispatcher.execute(config);
      await this.state.completeTask(taskId, output);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      console.error(`[workflow] Service task ${taskId} failed: ${msg}`);
      await this.state.failTask(taskId, msg);
    }
  }

  private async executeAiTask(
    taskId: string,
    nodeType: string,
    config: Record<string, unknown>,
    variables: Record<string, unknown>,
  ): Promise<void> {
    try {
      const handler = getAiHandler(nodeType, variables);
      const output = await handler.execute(config);
      console.log(`[workflow] AI task ${taskId} (${nodeType}) completed`);
      await this.state.completeTask(taskId, output);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      console.error(`[workflow] AI task ${taskId} (${nodeType}) failed: ${msg}`);
      await this.state.failTask(taskId, msg);
    }
  }

  /** Map node type to TaskType. */
  classifyTaskType(nodeType: string): TaskType {
    if (nodeType === 'trigger') return 'service_task';
    if (['assignment', 'approval', 'user_task'].includes(nodeType)) return 'user_task';
    if (nodeType === 'task_pool') return 'user_task';
    if (nodeType === 'escalation') return 'user_task';
    if (nodeType.startsWith('ai_')) return 'service_task';
    if (['action', 'service_task', 'automation'].includes(nodeType)) return 'service_task';
    if (['wait', 'timer', 'timer_event'].includes(nodeType)) return 'timer_event';
    if (['condition', 'gateway', 'exclusive_gateway', 'parallel_gateway'].includes(nodeType)) return 'gateway';
    return 'user_task';
  }

  /** Whether a task type blocks workflow progression until completed. */
  isBlockingTask(taskType: TaskType): boolean {
    return taskType === 'user_task' || taskType === 'timer_event';
  }
}
