/** Execution logger — records audit trail for every workflow node execution. */

import { eq } from 'drizzle-orm';
import { db } from '@/db';
import { wfExecutionLogs, type WfExecutionLog } from './schema';
import type { NodeExecutionStatus } from '../domain/types';

export class ExecutionLogger {
  async logStart(params: {
    instanceId: string;
    nodeId: string;
    nodeType: string;
    nodeLabel?: string | null;
    inputSnapshot?: Record<string, unknown>;
  }): Promise<WfExecutionLog> {
    const [entry] = await db
      .insert(wfExecutionLogs)
      .values({
        workflowInstanceId: params.instanceId,
        nodeId: params.nodeId,
        nodeType: params.nodeType,
        nodeLabel: params.nodeLabel ?? null,
        status: 'started' satisfies NodeExecutionStatus,
        inputSnapshot: params.inputSnapshot ?? null,
        startedAt: new Date(),
      })
      .returning();
    return entry;
  }

  async logComplete(
    logEntryId: string,
    outputSnapshot?: Record<string, unknown>,
  ): Promise<void> {
    const now = new Date();
    // Fetch start time for duration calc
    const [entry] = await db
      .select({ startedAt: wfExecutionLogs.startedAt })
      .from(wfExecutionLogs)
      .where(eq(wfExecutionLogs.id, logEntryId));

    const durationMs = entry?.startedAt
      ? now.getTime() - new Date(entry.startedAt).getTime()
      : null;

    await db
      .update(wfExecutionLogs)
      .set({
        status: 'completed' satisfies NodeExecutionStatus,
        completedAt: now,
        outputSnapshot: outputSnapshot ?? null,
        durationMs,
      })
      .where(eq(wfExecutionLogs.id, logEntryId));
  }

  async logFailure(logEntryId: string, errorMessage: string): Promise<void> {
    const now = new Date();
    const [entry] = await db
      .select({ startedAt: wfExecutionLogs.startedAt })
      .from(wfExecutionLogs)
      .where(eq(wfExecutionLogs.id, logEntryId));

    const durationMs = entry?.startedAt
      ? now.getTime() - new Date(entry.startedAt).getTime()
      : null;

    await db
      .update(wfExecutionLogs)
      .set({
        status: 'failed' satisfies NodeExecutionStatus,
        completedAt: now,
        errorMessage,
        durationMs,
      })
      .where(eq(wfExecutionLogs.id, logEntryId));
  }

  async logSkip(params: {
    instanceId: string;
    nodeId: string;
    nodeType: string;
    nodeLabel?: string | null;
    reason: string;
  }): Promise<WfExecutionLog> {
    const now = new Date();
    const [entry] = await db
      .insert(wfExecutionLogs)
      .values({
        workflowInstanceId: params.instanceId,
        nodeId: params.nodeId,
        nodeType: params.nodeType,
        nodeLabel: params.nodeLabel ?? null,
        status: 'skipped' satisfies NodeExecutionStatus,
        errorMessage: params.reason,
        startedAt: now,
        completedAt: now,
        durationMs: 0,
      })
      .returning();
    return entry;
  }
}
