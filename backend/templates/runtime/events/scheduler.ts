/**
 * Cron-trigger scheduler — fires workflows whose top-level
 * `trigger: {kind:"schedule", cron}` is due.
 *
 * Serverless-first: no daemon. runDueSchedules() is invoked from
 * /api/cron/tick (Vercel cron / external pinger). Due-ness is computed by
 * the self-written 5-field matcher in ./cron against per-workflow
 * last-run state in the forge_schedules table (workflow_id UNIQUE,
 * last_run_at, enabled) — the same table the legacy interval sweep uses,
 * so each due window fires exactly once across both mechanisms.
 *
 * Legacy `definition.trigger.type === "schedule"` workflows (interval
 * shorthand, no real cron) are still handled by the interval sweep in
 * api-cron/route.ts; this module only owns the exact-cron contract.
 */

import { db } from "@/db";
import { sql } from "drizzle-orm";
import { isDue } from "./cron";
import { getTriggerContract } from "./triggers";

function _rows(res: unknown): any[] {
  return Array.isArray(res) ? res : ((res as { rows?: any[] })?.rows ?? []);
}

export async function runDueSchedules(
  now: Date = new Date(),
): Promise<{ checked: number; fired: string[] }> {
  const fired: string[] = [];

  let wfmod: typeof import("@/lib/workflows");
  try {
    wfmod = await import("@/lib/workflows");
  } catch (err) {
    console.warn("[scheduler] workflow runtime unavailable:", err);
    return { checked: 0, fired };
  }

  const all = await wfmod.listWorkflows();
  const scheduled = all
    .map((wf) => ({ wf, trig: getTriggerContract(wf) }))
    .filter((x): x is { wf: (typeof all)[number]; trig: { kind: "schedule"; cron: string } } =>
      x.trig?.kind === "schedule",
    );

  for (const { wf, trig } of scheduled) {
    try {
      let lastRunAt: Date | null = null;
      let enabled = true;
      try {
        const res: any = await db.execute(sql`
          SELECT last_run_at, enabled FROM forge_schedules
          WHERE workflow_id = ${wf.id} LIMIT 1
        `);
        const row = _rows(res)[0];
        if (row) {
          enabled = row.enabled !== false;
          lastRunAt = row.last_run_at ? new Date(row.last_run_at) : null;
        }
      } catch {
        /* table missing on an older app — treat as never-run */
      }
      if (!enabled) continue;
      if (!isDue(trig.cron, lastRunAt, now)) continue;

      // Record the run BEFORE dispatch so a slow workflow can't be
      // double-fired by an overlapping cron tick.
      try {
        await db.execute(sql`
          INSERT INTO forge_schedules (id, workflow_id, cadence, last_run_at, enabled)
          VALUES (gen_random_uuid(), ${wf.id}, ${trig.cron}, ${now.toISOString()}::timestamp, true)
          ON CONFLICT (workflow_id)
          DO UPDATE SET last_run_at = ${now.toISOString()}::timestamp, cadence = ${trig.cron}
        `);
      } catch (err) {
        console.warn(`[scheduler] could not record run for ${wf.id}:`, err);
      }

      await wfmod.triggerWorkflow(wf.id, {
        scheduledAt: now.toISOString(),
        trigger: "schedule",
      });
      fired.push(wf.id);
    } catch (err) {
      console.warn(`[scheduler] schedule failed for ${wf.id}:`, err);
    }
  }

  return { checked: scheduled.length, fired };
}
