/** Timer scheduler — background poller that completes expired wait tasks and checks SLAs. */

import { eq, and, inArray, lte, isNotNull } from 'drizzle-orm';
import { db } from '@/db';
import { wfInstances, wfTaskInstances } from '../infrastructure/schema';
import type { WorkflowNode, WorkflowEdge } from '../domain/types';

// Duration parsing patterns
const DURATION_PATTERNS: [RegExp, string][] = [
  [/(\d+)\s*(?:seconds?|s)\b/i, 'seconds'],
  [/(\d+)\s*(?:minutes?|m)\b/i, 'minutes'],
  [/(\d+)\s*(?:hours?|h)\b/i, 'hours'],
  [/(\d+)\s*(?:days?|d)\b/i, 'days'],
];

const UNIT_TO_MS: Record<string, number> = {
  seconds: 1_000,
  minutes: 60_000,
  hours: 3_600_000,
  days: 86_400_000,
};

/** Parse a human-readable duration string into milliseconds. */
export function parseDuration(durationStr: string): number {
  if (!durationStr) return 3_600_000; // default 1 hour

  for (const [pattern, unit] of DURATION_PATTERNS) {
    const match = pattern.exec(durationStr);
    if (match) {
      const value = parseInt(match[1], 10);
      return value * UNIT_TO_MS[unit];
    }
  }

  // Fallback: try to parse as a number of seconds
  const asNum = parseInt(durationStr, 10);
  if (!isNaN(asNum)) return asNum * 1_000;

  console.warn(`[workflow] Could not parse duration "${durationStr}", defaulting to 1 hour`);
  return 3_600_000;
}

export class TimerScheduler {
  /** Check for expired timer tasks and complete them. */
  async checkExpiredTimers(): Promise<void> {
    const now = new Date();

    const timerTasks = await db
      .select()
      .from(wfTaskInstances)
      .where(
        and(
          eq(wfTaskInstances.taskType, 'timer_event'),
          inArray(wfTaskInstances.status, ['pending', 'assigned']),
        ),
      );

    for (const task of timerTasks) {
      const resumeAtStr = (task.inputData as Record<string, unknown>)?.resume_at as string;
      if (!resumeAtStr) continue;

      let resumeAt: Date;
      try {
        resumeAt = new Date(resumeAtStr);
      } catch {
        continue;
      }

      if (now >= resumeAt) {
        console.log(`[workflow] Timer expired for task ${task.id} (node=${task.nodeId}), completing`);
        await db
          .update(wfTaskInstances)
          .set({
            status: 'completed',
            completedAt: now,
            outputData: { timer_expired: true, resume_at: resumeAtStr },
            updatedAt: now,
          })
          .where(eq(wfTaskInstances.id, task.id));

        // Advance the workflow
        await this.advanceWorkflow(task.workflowInstanceId, task.nodeId);
      }
    }
  }

  /** Check for SLA breaches on overdue user tasks. */
  async checkSlaBreaches(): Promise<void> {
    const now = new Date();

    const overdueTasks = await db
      .select()
      .from(wfTaskInstances)
      .where(
        and(
          eq(wfTaskInstances.taskType, 'user_task'),
          inArray(wfTaskInstances.status, ['pending', 'assigned', 'active']),
          isNotNull(wfTaskInstances.dueAt),
          lte(wfTaskInstances.dueAt, now),
        ),
      );

    for (const task of overdueTasks) {
      const config = ((task.inputData as Record<string, unknown>)?.config ?? {}) as Record<string, unknown>;
      const escalateTo = config.escalateTo as string;

      if (escalateTo) {
        console.log(
          `[workflow] SLA breach for task ${task.id} (node=${task.nodeId}) — escalating to ${escalateTo}`,
        );
        const inputData = { ...(task.inputData as Record<string, unknown>), sla_breached: true, escalated_to: escalateTo };
        await db
          .update(wfTaskInstances)
          .set({ inputData, updatedAt: new Date() })
          .where(eq(wfTaskInstances.id, task.id));
      }
    }
  }

  /** After completing a timer task, advance the workflow. */
  private async advanceWorkflow(instanceId: string, completedNodeId: string): Promise<void> {
    try {
      const [instance] = await db
        .select()
        .from(wfInstances)
        .where(eq(wfInstances.id, instanceId));

      if (!instance) return;

      // Lazy import to avoid circular dependency
      const { WorkflowEngine } = await import('./workflow-engine');
      const engine = new WorkflowEngine();

      const definition = engine.loadDefinition(instance.workflowId);
      if (!definition) return;

      const nodes = definition.definition.nodes;
      const edges = definition.definition.edges;

      const nextNodeIds = edges
        .filter((e: WorkflowEdge) => e.source === completedNodeId)
        .map((e: WorkflowEdge) => e.target);

      if (nextNodeIds.length > 0) {
        await engine.executeNodes({
          instanceId,
          nodeIds: nextNodeIds,
          nodes,
          edges,
        });
      } else {
        // Check completion
        const pending = await db
          .select()
          .from(wfTaskInstances)
          .where(
            and(
              eq(wfTaskInstances.workflowInstanceId, instanceId),
              inArray(wfTaskInstances.status, ['pending', 'assigned', 'active']),
            ),
          );
        if (pending.length === 0) {
          await db
            .update(wfInstances)
            .set({ status: 'completed', completedAt: new Date(), updatedAt: new Date() })
            .where(eq(wfInstances.id, instanceId));
        }
      }
    } catch (error) {
      console.error(`[workflow] Failed to advance workflow after timer completion: ${error}`);
    }
  }
}
