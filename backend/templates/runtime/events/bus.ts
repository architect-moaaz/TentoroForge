/**
 * Postgres-backed event bus — durable "when X happens, do Y".
 *
 * emitEvent(type, {entity, entityId, payload}) inserts a forge_events row.
 * processPendingEvents(limit) claims unprocessed rows (UPDATE … FOR UPDATE
 * SKIP LOCKED, oldest first — safe under concurrent serverless
 * invocations) and, per event:
 *
 *   1. dispatches every workflow whose `trigger: {kind:"event", event}`
 *      matches (findWorkflowsForEvent), and
 *   2. resumes any execution paused on a wait_for_event node awaiting
 *      that event (workflow_tasks rows with task_type='wait_for_event').
 *
 * Serverless-first: NO long-lived LISTEN/NOTIFY daemon. Processing runs
 * inline after each emit (fire-and-forget with error logging) and from
 * the /api/cron/tick sweeper, which retries anything the inline pass
 * missed (cold start crash, timeout).
 *
 * Every failure here is non-fatal — a bus outage must never fail the
 * write or workflow that emitted the event.
 */

import { db } from "@/db";
import { sql } from "drizzle-orm";
import {
  findWorkflowsForEvent,
  buildResumeInput,
  buildTimeoutResumeInput,
  WAITING_EVENT_VAR,
} from "./triggers";

export interface EmitOpts {
  entity?: string | null;
  entityId?: string | null;
  payload?: Record<string, unknown>;
}

export interface ForgeEventRow {
  id: string;
  type: string;
  entity: string | null;
  entity_id: string | null;
  payload: Record<string, unknown>;
}

function _rows(res: unknown): any[] {
  return Array.isArray(res) ? res : ((res as { rows?: any[] })?.rows ?? []);
}

/**
 * Insert one event row. Returns {id} or null when the table is missing
 * (older generated app) / the insert fails — never throws.
 */
export async function emitEvent(
  type: string,
  opts: EmitOpts = {},
): Promise<{ id: string } | null> {
  const t = String(type ?? "").trim();
  if (!t) return null;
  try {
    const res: any = await db.execute(sql`
      INSERT INTO forge_events (id, type, entity, entity_id, payload, created_at)
      VALUES (
        gen_random_uuid(),
        ${t},
        ${opts.entity ?? null},
        ${opts.entityId ?? null},
        ${JSON.stringify(opts.payload ?? {})}::jsonb,
        NOW()
      )
      RETURNING id
    `);
    const row = _rows(res)[0];
    return row?.id ? { id: String(row.id) } : null;
  } catch (err) {
    console.warn(`[events] emitEvent(${t}) failed (non-fatal):`, err);
    return null;
  }
}

/**
 * Emit + kick inline processing (fire-and-forget). The kick is
 * re-entrancy-guarded so an event emitted DURING processing (e.g. by an
 * emit_event node) schedules one more pass instead of stacking
 * concurrent loops; anything still missed is swept by /api/cron/tick.
 */
export async function emitEventAndProcess(
  type: string,
  opts: EmitOpts = {},
): Promise<{ id: string } | null> {
  const row = await emitEvent(type, opts);
  if (row) {
    void _kickProcessing().catch((err) =>
      console.warn("[events] inline processing failed (cron will sweep):", err),
    );
  }
  return row;
}

let _processing = false;
let _rerun = false;

async function _kickProcessing(): Promise<void> {
  if (_processing) {
    _rerun = true;
    return;
  }
  _processing = true;
  try {
    do {
      _rerun = false;
      await processPendingEvents();
    } while (_rerun);
  } finally {
    _processing = false;
  }
}

/**
 * Claim up to `limit` unprocessed events and dispatch them. Returns
 * {claimed, dispatched, resumed, errors}. Safe to call from anywhere —
 * the claim is atomic, so concurrent invocations split the backlog
 * instead of double-dispatching it.
 */
export async function processPendingEvents(limit = 50): Promise<{
  claimed: number;
  dispatched: number;
  resumed: number;
  errors: number;
}> {
  const out = { claimed: 0, dispatched: 0, resumed: 0, errors: 0 };

  let claimed: ForgeEventRow[] = [];
  try {
    const res: any = await db.execute(sql`
      UPDATE forge_events SET processed_at = NOW()
      WHERE id IN (
        SELECT id FROM forge_events
        WHERE processed_at IS NULL
        ORDER BY created_at
        LIMIT ${limit}
        FOR UPDATE SKIP LOCKED
      )
      RETURNING id, type, entity, entity_id, payload
    `);
    claimed = _rows(res) as ForgeEventRow[];
  } catch (err) {
    // Table missing (older app) or DB unavailable — non-fatal.
    console.warn("[events] processPendingEvents claim failed (non-fatal):", err);
    return out;
  }
  out.claimed = claimed.length;
  if (!claimed.length) return out;

  // Dynamic import mirrors event-registry.ts — avoids a static cycle
  // (workflows/index.ts registers the emit_event node, which imports us).
  let wfmod: typeof import("@/lib/workflows") | null = null;
  try {
    wfmod = await import("@/lib/workflows");
  } catch {
    console.warn("[events] workflow runtime unavailable — events claimed but not dispatched");
  }

  for (const evt of claimed) {
    try {
      if (wfmod) {
        out.dispatched += await _dispatchEvent(wfmod, evt);
        out.resumed += await _resumeWaiters(wfmod, evt);
      }
    } catch (err) {
      out.errors += 1;
      const msg = err instanceof Error ? err.message : String(err);
      console.warn(`[events] dispatch failed for ${evt.type} (${evt.id}):`, err);
      try {
        await db.execute(sql`
          UPDATE forge_events SET error = ${msg.slice(0, 2000)} WHERE id = ${evt.id}::uuid
        `);
      } catch {
        /* observability write only — never escalate */
      }
    }
  }
  return out;
}

/** Start every workflow whose event trigger matches. Returns count started. */
async function _dispatchEvent(
  wfmod: typeof import("@/lib/workflows"),
  evt: ForgeEventRow,
): Promise<number> {
  const all = await wfmod.listWorkflows();
  const matching = findWorkflowsForEvent(all, evt.type);
  let started = 0;
  for (const wf of matching) {
    const payload =
      evt.payload && typeof evt.payload === "object" ? evt.payload : {};
    // Payload fields at the top level (so {{entity.id}}-style bindings
    // resolve), plus the event envelope for explicit reads.
    const input: Record<string, unknown> = {
      ...payload,
      event: evt.type,
      entityType: evt.entity ?? undefined,
      entityId: evt.entity_id ?? (payload as any)?.entity?.id ?? undefined,
    };
    const user = (payload as { user?: { id: string; role?: string; email?: string } }).user;
    // triggerWorkflow persists a pending task itself if the run pauses.
    const result = await wfmod.triggerWorkflow(wf.id, input, user);
    started += 1;
    if (result?.status === "failed") {
      throw new Error(`workflow ${wf.id} failed: ${result.error ?? "unknown"}`);
    }
  }
  return started;
}

/**
 * Resume executions paused on a wait_for_event node awaiting this event.
 *
 * The pause was persisted through the SAME mechanism as human tasks
 * (persistPendingTask → workflow_tasks, task_type='wait_for_event',
 * process_variables carrying __waiting_event). Resume mirrors the
 * /api/workflows/[id]/execute resume path: stored process_variables +
 * completion markers → triggerWorkflow re-walks the graph, the T5
 * short-circuit replays completed nodes, and the walk continues past the
 * wait node with the event payload as its output.
 */
async function _resumeWaiters(
  wfmod: typeof import("@/lib/workflows"),
  evt: ForgeEventRow,
): Promise<number> {
  let waiters: Array<{
    id: string;
    workflow_id: string;
    node_id: string;
    process_variables: unknown;
  }> = [];
  try {
    const res: any = await db.execute(sql`
      SELECT id, workflow_id, node_id, process_variables
      FROM workflow_tasks
      WHERE status = 'pending'
        AND task_type = 'wait_for_event'
        AND process_variables->>${WAITING_EVENT_VAR} = ${evt.type}
      ORDER BY created_at
    `);
    waiters = _rows(res);
  } catch (err) {
    console.warn("[events] wait_for_event lookup failed (non-fatal):", err);
    return 0;
  }

  let resumed = 0;
  for (const task of waiters) {
    const pv =
      typeof task.process_variables === "string"
        ? JSON.parse(task.process_variables || "{}")
        : ((task.process_variables as Record<string, unknown>) ?? {});
    const payload =
      evt.payload && typeof evt.payload === "object" ? evt.payload : {};
    const input = buildResumeInput(pv, task.node_id, evt.type, payload);

    const result = await wfmod.triggerWorkflow(task.workflow_id, input);
    // Mark the wait row completed regardless of downstream outcome —
    // matches the /execute route, which completes the task row after the
    // resume dispatch. A failed downstream run is the run's own failure.
    try {
      await db.execute(sql`
        UPDATE workflow_tasks
        SET status = 'completed',
            completed_at = NOW(),
            decision = ${"event:" + evt.type},
            response_data = ${JSON.stringify({ event: evt.type, eventId: evt.id })}
        WHERE id = ${task.id}::uuid
      `);
    } catch {
      // response_data column may not exist on older apps — retry minimal.
      try {
        await db.execute(sql`
          UPDATE workflow_tasks SET status = 'completed', completed_at = NOW()
          WHERE id = ${task.id}::uuid
        `);
      } catch (err2) {
        console.warn("[events] could not complete wait task:", err2);
      }
    }
    resumed += 1;
    if (result?.status === "failed") {
      throw new Error(
        `resume of ${task.workflow_id} (task ${task.id}) failed: ${result.error ?? "unknown"}`,
      );
    }
  }
  return resumed;
}

/**
 * Resume executions whose wait_for_event timeout elapsed (task row still
 * pending, due_at in the past — due_at was set from the node's timeoutMs
 * at pause time). The wait node's cached output carries `timedOut: true`
 * and no event payload, so downstream Conditionals can branch onto the
 * escalation path. Called from the /api/cron/tick sweep; never throws.
 */
export async function resumeExpiredWaits(now: Date = new Date()): Promise<number> {
  let expired: Array<{
    id: string;
    workflow_id: string;
    node_id: string;
    process_variables: unknown;
  }> = [];
  try {
    const res: any = await db.execute(sql`
      SELECT id, workflow_id, node_id, process_variables
      FROM workflow_tasks
      WHERE status = 'pending'
        AND task_type = 'wait_for_event'
        AND due_at IS NOT NULL
        AND due_at <= ${now.toISOString()}::timestamptz
      ORDER BY due_at
    `);
    expired = _rows(res);
  } catch (err) {
    console.warn("[events] expired-wait lookup failed (non-fatal):", err);
    return 0;
  }
  if (!expired.length) return 0;

  let wfmod: typeof import("@/lib/workflows") | null = null;
  try {
    wfmod = await import("@/lib/workflows");
  } catch {
    console.warn("[events] workflow runtime unavailable — expired waits left pending");
    return 0;
  }

  let resumed = 0;
  for (const task of expired) {
    try {
      const pv =
        typeof task.process_variables === "string"
          ? JSON.parse(task.process_variables || "{}")
          : ((task.process_variables as Record<string, unknown>) ?? {});
      const awaited = String(pv?.[WAITING_EVENT_VAR] ?? "");
      const input = buildTimeoutResumeInput(pv, task.node_id, awaited);

      // Complete the task row FIRST so a slow/failed resume can never
      // double-fire on the next sweep (mirrors the scheduler's
      // record-before-dispatch rule).
      try {
        await db.execute(sql`
          UPDATE workflow_tasks
          SET status = 'completed', completed_at = NOW(), decision = 'timeout'
          WHERE id = ${task.id}::uuid AND status = 'pending'
        `);
      } catch (err) {
        console.warn("[events] could not complete expired wait task:", err);
        continue;
      }

      await wfmod.triggerWorkflow(task.workflow_id, input);
      resumed += 1;
    } catch (err) {
      console.warn(`[events] timeout resume failed for task ${task.id}:`, err);
    }
  }
  return resumed;
}
