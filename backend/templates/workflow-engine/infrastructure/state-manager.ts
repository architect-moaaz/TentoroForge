/** State manager — manages workflow instance lifecycle and persistence. */

import { eq, and, inArray } from 'drizzle-orm';
import { db } from '@/db';
import {
  wfInstances,
  wfTaskInstances,
  type WfInstance,
  type WfTaskInstance,
} from './schema';
import type {
  WorkflowInstanceStatus,
  TaskInstanceStatus,
  TaskType,
} from '../domain/types';

export class StateManager {
  // --- Instance management ---

  async createInstance(params: {
    workflowId: string;
    workflowName: string;
    initiatedBy?: string | null;
    variables?: Record<string, unknown>;
  }): Promise<WfInstance> {
    const [instance] = await db
      .insert(wfInstances)
      .values({
        workflowId: params.workflowId,
        workflowName: params.workflowName,
        status: 'created',
        initiatedBy: params.initiatedBy ?? null,
        variables: params.variables ?? {},
        currentNodeIds: [],
      })
      .returning();
    return instance;
  }

  async getInstance(instanceId: string): Promise<WfInstance | undefined> {
    const [instance] = await db
      .select()
      .from(wfInstances)
      .where(eq(wfInstances.id, instanceId));
    return instance;
  }

  async transitionInstance(
    instanceId: string,
    newStatus: WorkflowInstanceStatus,
    errorMessage?: string,
  ): Promise<void> {
    const now = new Date();
    const updates: Record<string, unknown> = {
      status: newStatus,
      updatedAt: now,
    };

    if (newStatus === 'running') {
      updates.startedAt = now;
    }
    if (newStatus === 'completed' || newStatus === 'failed' || newStatus === 'cancelled') {
      updates.completedAt = now;
    }
    if (errorMessage) {
      updates.errorMessage = errorMessage;
    }

    await db.update(wfInstances).set(updates).where(eq(wfInstances.id, instanceId));
  }

  async updateCurrentNodes(instanceId: string, nodeIds: string[]): Promise<void> {
    await db
      .update(wfInstances)
      .set({ currentNodeIds: nodeIds, updatedAt: new Date() })
      .where(eq(wfInstances.id, instanceId));
  }

  async setVariable(instanceId: string, key: string, value: unknown): Promise<void> {
    const instance = await this.getInstance(instanceId);
    if (!instance) return;
    const variables = { ...(instance.variables ?? {}), [key]: value };
    await db
      .update(wfInstances)
      .set({ variables, updatedAt: new Date() })
      .where(eq(wfInstances.id, instanceId));
  }

  async getVariables(instanceId: string): Promise<Record<string, unknown>> {
    const instance = await this.getInstance(instanceId);
    return (instance?.variables as Record<string, unknown>) ?? {};
  }

  // --- Task instance management ---

  async createTask(params: {
    workflowInstanceId: string;
    nodeId: string;
    nodeLabel?: string | null;
    taskType: TaskType;
    assigneeId?: string | null;
    assigneeType?: string | null;
    inputData?: Record<string, unknown>;
    dueAt?: Date | null;
  }): Promise<WfTaskInstance> {
    const [task] = await db
      .insert(wfTaskInstances)
      .values({
        workflowInstanceId: params.workflowInstanceId,
        nodeId: params.nodeId,
        nodeLabel: params.nodeLabel ?? null,
        taskType: params.taskType,
        status: params.assigneeId ? 'assigned' : 'pending',
        assigneeId: params.assigneeId ?? null,
        assigneeType: params.assigneeType ?? null,
        inputData: params.inputData ?? {},
        dueAt: params.dueAt ?? null,
      })
      .returning();
    return task;
  }

  async getTask(taskId: string): Promise<WfTaskInstance | undefined> {
    const [task] = await db
      .select()
      .from(wfTaskInstances)
      .where(eq(wfTaskInstances.id, taskId));
    return task;
  }

  async completeTask(taskId: string, outputData?: Record<string, unknown>): Promise<void> {
    const updates: Record<string, unknown> = {
      status: 'completed' as TaskInstanceStatus,
      completedAt: new Date(),
      updatedAt: new Date(),
    };
    if (outputData) {
      updates.outputData = outputData;
    }
    await db.update(wfTaskInstances).set(updates).where(eq(wfTaskInstances.id, taskId));
  }

  async failTask(taskId: string, errorMessage: string): Promise<void> {
    await db
      .update(wfTaskInstances)
      .set({
        status: 'failed',
        errorMessage,
        completedAt: new Date(),
        updatedAt: new Date(),
      })
      .where(eq(wfTaskInstances.id, taskId));
  }

  async listPendingTasksForInstance(instanceId: string): Promise<WfTaskInstance[]> {
    return db
      .select()
      .from(wfTaskInstances)
      .where(
        and(
          eq(wfTaskInstances.workflowInstanceId, instanceId),
          inArray(wfTaskInstances.status, ['pending', 'assigned', 'active']),
        ),
      );
  }

  async cancelPendingTasks(instanceId: string): Promise<void> {
    const now = new Date();
    await db
      .update(wfTaskInstances)
      .set({ status: 'cancelled', completedAt: now, updatedAt: now })
      .where(
        and(
          eq(wfTaskInstances.workflowInstanceId, instanceId),
          inArray(wfTaskInstances.status, ['pending', 'assigned', 'active']),
        ),
      );
  }
}
