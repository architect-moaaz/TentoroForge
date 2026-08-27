/**
 * Escalation Runner — cron-driven reminders and escalations for pending approvals.
 *
 * Generated apps run this via a scheduled job:
 *   - Vercel cron (vercel.json → /api/cron/escalations)
 *   - GitHub Actions scheduled workflow
 *   - A separate worker process
 *
 * Usage:
 *   import { processEscalations } from "@/lib/workflows/escalation";
 *   await processEscalations(db, pendingApprovals, notifyFn);
 */

import type { StageV2 } from "./types";
import { appendAuditEntry, getAuditTrailForRecord } from "./audit-log";

export interface PendingApproval {
  workflowId: string;
  recordId: string;
  stage: StageV2;
  pendingSince: string;     // ISO 8601 — when entered this stage
}

/**
 * Has this reminder/escalation already been sent for this threshold?
 *
 * The audit trail already records every send with its `afterDays`, so it is
 * the natural idempotency key — no new state, no new table. Needed because
 * the threshold test is now `>=` rather than `===`: without a dedupe, a
 * daily cron would re-send every day once the age passed the threshold.
 *
 * Fails OPEN (returns false) if the trail cannot be read: sending a duplicate
 * reminder is a far smaller harm than silently dropping an SLA escalation.
 */
async function _alreadyFired(
  db: any,
  p: PendingApproval,
  action: string,
  afterDays: number,
): Promise<boolean> {
  try {
    const trail = await getAuditTrailForRecord(db, p.workflowId, p.recordId);
    return (trail ?? []).some(
      (e: any) => e?.action === action && e?.metadata?.afterDays === afterDays,
    );
  } catch {
    return false;
  }
}

/**
 * Process pending approvals: send reminders and escalate as configured
 * on each stage's `reminders` and `escalations` arrays.
 *
 * @param db      Your DB connection
 * @param pending Array of currently-pending approvals (query your DB for these)
 * @param notify  Channel-agnostic notification function — generated apps wire
 *                this to SMTP / push / Slack as appropriate
 */
export async function processEscalations(
  db: any,
  pending: PendingApproval[],
  notify: (channel: string, target: string, payload: any) => Promise<void>,
): Promise<void> {
  for (const p of pending) {
    const ageMs = Date.now() - new Date(p.pendingSince).getTime();
    const ageDays = Math.floor(ageMs / (24 * 3600 * 1000));

    // Reminders.
    //
    // `ageDays === afterDays` tests a THRESHOLD CROSSING as an equality on a
    // sampled value, which fails in both directions: if the cron misses its
    // exact day (a deploy, a restart, an outage) the reminder is lost
    // FOREVER, and if the cron runs hourly the same reminder fires 24 times.
    // Use `>=` so a missed day still fires, and suppress duplicates against
    // the audit trail — which already records every send — so firing late
    // does not mean firing repeatedly.
    for (const reminder of p.stage.reminders ?? []) {
      if (ageDays >= reminder.afterDays &&
          !(await _alreadyFired(db, p, "reminder-sent", reminder.afterDays))) {
        await notify(reminder.channel, "approver", {
          workflowId: p.workflowId, recordId: p.recordId,
          message: `Reminder: ${p.stage.name} pending for ${ageDays} days.`,
        });
        await appendAuditEntry(db, {
          workflowId: p.workflowId, recordId: p.recordId,
          timestamp: new Date().toISOString(),
          actor: "system", action: "reminder-sent",
          metadata: { afterDays: reminder.afterDays, channel: reminder.channel, ageDays },
        });
      }
    }

    // Escalations — same threshold-crossing bug, same fix.
    for (const escalation of p.stage.escalations ?? []) {
      if (ageDays >= escalation.afterDays &&
          !(await _alreadyFired(db, p, "escalated", escalation.afterDays))) {
        await notify("email", "escalated", {
          workflowId: p.workflowId, recordId: p.recordId,
          escalateTo: escalation.escalateTo,
          message: `Escalated: ${p.stage.name} pending for ${ageDays} days.`,
        });
        await appendAuditEntry(db, {
          workflowId: p.workflowId, recordId: p.recordId,
          timestamp: new Date().toISOString(),
          actor: "system", action: "escalated",
          metadata: { afterDays: escalation.afterDays, escalateTo: escalation.escalateTo, ageDays },
        });
      }
    }
  }
}

/**
 * Scan the `workflow_tasks` table for pending tasks whose `due_at` is
 * in the past AND that carry an `escalate_to` — the escalation-policy
 * carry-through written by `persistPendingTask` when an upstream
 * escalation node fired. For each match, reassign the task's role to
 * `escalate_to`, clear the escalation policy so it doesn't fire again,
 * and emit a notification via the caller-supplied channel.
 *
 * Run alongside `processEscalations` from the same cron endpoint —
 * the two target different pending shapes (StageV2 tasks vs. the
 * `workflow_tasks` inbox rows).
 */
export async function processTaskEscalations(
  db: any,
  notify: (channel: string, target: string, payload: any) => Promise<void>,
): Promise<{ escalated: number; error?: string }> {
  // Best-effort — never throw. If workflow_tasks isn't present yet
  // (older generated app), silently no-op.
  try {
    const res: any = await db.execute(
      `SELECT id, workflow_id, node_label, escalate_to, assignee_role, entity_id
         FROM workflow_tasks
        WHERE status = 'pending'
          AND due_at IS NOT NULL
          AND due_at < NOW()
          AND escalate_to IS NOT NULL`,
    );
    const rows: any[] = res?.rows ?? res ?? [];
    let escalated = 0;
    for (const row of rows) {
      const target = row.escalate_to;
      if (!target) continue;
      await db.execute(
        `UPDATE workflow_tasks
            SET assignee_role = $1,
                escalate_to = NULL,
                due_at = NULL
          WHERE id = $2`,
        [target, row.id],
      );
      await notify("email", "escalated", {
        workflowId: row.workflow_id,
        recordId: row.entity_id,
        escalateTo: target,
        message: `Task "${row.node_label}" was reassigned to ${target} after SLA breach.`,
      });
      try {
        await appendAuditEntry(db, {
          workflowId: row.workflow_id,
          recordId: row.entity_id,
          timestamp: new Date().toISOString(),
          actor: "system",
          action: "task-escalated",
          metadata: { taskId: row.id, from: row.assignee_role, to: target },
        });
      } catch {
        // Audit failure is not a run failure.
      }
      escalated++;
    }
    return { escalated };
  } catch (err) {
    // A hard database failure must NOT look like a healthy run with nothing
    // to escalate.
    //
    // `{ escalated: 0 }` is exactly what an empty queue returns, so an
    // unreachable database — meaning every SLA in the app has silently
    // stopped being enforced — was indistinguishable from "all caught up".
    // Whatever runs this on a schedule had no way to alert on it.
    //
    // A missing workflow_tasks table (an older generated app) is still a
    // legitimate no-op; anything else is reported.
    const msg = String((err as any)?.message ?? err);
    const tableMissing = /no such table|does not exist|relation .* does not exist|undefined table/i.test(msg);
    if (tableMissing) {
      console.warn("[workflow] processTaskEscalations: workflow_tasks not present — nothing to do.");
      return { escalated: 0 };
    }
    console.error(
      "[workflow] processTaskEscalations FAILED — no SLA escalation ran this cycle. " +
      "Every overdue task remains unescalated.",
      err,
    );
    return { escalated: 0, error: msg };
  }
}
