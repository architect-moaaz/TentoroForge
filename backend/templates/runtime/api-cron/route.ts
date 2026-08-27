/**
 * GET|POST /api/cron/tick — fires schedule-triggered workflows that are due.
 *
 * Next.js apps have no background worker, so drive this from an external timer:
 * Vercel Cron, a crontab curl, or an uptime pinger. Each hit checks every
 * workflow whose trigger.type === "schedule", compares its cadence against the
 * last run (forge_schedules), and triggers the due ones. Optionally protect with
 * CRON_SECRET (Bearer header or ?secret=). Forge runtime — do not remove.
 */
import { listWorkflows, triggerWorkflow } from "@/lib/workflows";
import { initializeRuntime } from "@/lib/runtime-loader";
import { db } from "@/db";
import { forgeSchedules } from "@/db/schema/_forge_schedules";
import { eq } from "drizzle-orm";
import { runDueSchedules } from "@/lib/events/scheduler";
import { processPendingEvents, resumeExpiredWaits } from "@/lib/events/bus";
import { getTriggerContract } from "@/lib/events/triggers";

export const runtime = "nodejs";

/** Approximate a 5-field cron ("min hour dom mon dow") to a sweep interval (ms).
 *  A schedule workflow is a periodic sweep, so we map the cron to how OFTEN it
 *  runs rather than an exact wall-clock time. */
function cronToMs(cron: string): number {
  const p = cron.trim().split(/\s+/);
  const mn = p[0] ?? "*";
  const hr = p[1] ?? "*";
  if (mn.startsWith("*/")) return Math.max(1, Number(mn.slice(2)) || 1) * 60000;
  if (hr.startsWith("*/")) return Math.max(1, Number(hr.slice(2)) || 1) * 3600000;
  if (mn === "*") return 60000;                       // every minute
  if (hr === "*" && /^\d+$/.test(mn)) return 3600000; // hourly (at minute N)
  if (/^\d+$/.test(hr)) return 86400000;              // daily (at H:M)
  return 3600000;
}

/** Resolve a schedule trigger's cadence to milliseconds. Accepts a cron string
 *  (editor), intervalMinutes (number), or shorthand "hourly"/"daily"/"weekly"/
 *  "30m"/"6h"/"1d". Defaults to hourly. */
function intervalMs(trigger: any): number {
  const t = trigger || {};
  if (typeof t.cron === "string" && t.cron.trim()) return cronToMs(t.cron);
  if (typeof t.intervalMinutes === "number" && t.intervalMinutes > 0) return t.intervalMinutes * 60000;
  const s = String(t.schedule ?? t.every ?? t.cadence ?? "").toLowerCase();
  if (/week/.test(s)) return 604800000;
  if (/day|daily/.test(s)) return 86400000;
  if (/hour|hourly/.test(s)) return 3600000;
  const m = s.match(/(\d+)\s*(mins?|m|hours?|hrs?|h|days?|d)/);
  if (m) {
    const n = Number(m[1]);
    const u = m[2][0];
    return n * (u === "h" ? 3600000 : u === "d" ? 86400000 : 60000);
  }
  return 3600000;
}

/** True if the workflow is schedule-triggered (definition.trigger OR a trigger node). */
function isScheduled(wf: any): boolean {
  if (wf?.definition?.trigger?.type === "schedule") return true;
  return (wf?.definition?.nodes || []).some(
    (n: any) => (n?.type === "trigger" || n?.data?.nodeType === "trigger") && n?.data?.config?.type === "schedule",
  );
}

/** Merge the schedule cadence config from the trigger node + definition.trigger. */
function scheduleConfig(wf: any): any {
  const node = (wf?.definition?.nodes || []).find(
    (n: any) => n?.type === "trigger" || n?.data?.nodeType === "trigger",
  );
  return { ...(node?.data?.config || {}), ...(wf?.definition?.trigger || {}) };
}

async function handler(req: Request): Promise<Response> {
  // Read via getSecret so admins can rotate/set the cron secret from
  // /settings/integrations without a restart. Falls back to process.env
  // when the resolver / DB is unavailable.
  const { getSecret } = await import("@/lib/integrations/resolver");
  const secret = await getSecret("cron", "CRON_SECRET");
  if (secret) {
    const auth = req.headers.get("authorization") || "";
    const qs = new URL(req.url).searchParams.get("secret");
    if (auth !== `Bearer ${secret}` && qs !== secret) {
      return new Response("Unauthorized", { status: 401 });
    }
  }

  await initializeRuntime();

  // R2: exact-cron schedules (top-level trigger {kind:"schedule", cron}) —
  // real 5-field matcher against forge_schedules last-run state.
  let cronFired: string[] = [];
  try {
    cronFired = (await runDueSchedules(new Date())).fired;
  } catch (err) {
    console.warn("[cron] runDueSchedules failed:", err);
  }

  // R1: sweep the durable event bus for anything the inline (fire-and-
  // forget) pass missed — crashed invocation, cold-start timeout, etc.
  let events: { claimed: number; dispatched: number; resumed: number; errors: number } | null = null;
  try {
    events = await processPendingEvents();
  } catch (err) {
    console.warn("[cron] processPendingEvents failed:", err);
  }

  // R3 follow-up: wait_for_event timeouts — resume past-due waits with a
  // timedOut marker so escalation branches fire instead of hanging forever.
  let timedOut = 0;
  try {
    timedOut = await resumeExpiredWaits(new Date());
  } catch (err) {
    console.warn("[cron] resumeExpiredWaits failed:", err);
  }

  const all = await listWorkflows();
  // Legacy interval-approximated sweep. Workflows carrying the NEW exact
  // cron contract are excluded — runDueSchedules above owns those, and
  // double-sweeping would fire them twice per due window.
  const scheduled = (all as any[]).filter(
    (wf) => isScheduled(wf) && getTriggerContract(wf)?.kind !== "schedule",
  );
  const now = Date.now();
  const fired: string[] = [];

  for (const wf of scheduled) {
    const iv = intervalMs(scheduleConfig(wf));
    try {
      const rows = await db.select().from(forgeSchedules).where(eq(forgeSchedules.workflowId, wf.id)).limit(1);
      const sched = rows[0];
      if (sched && sched.enabled === false) continue;
      const last = sched?.lastRunAt ? new Date(sched.lastRunAt).getTime() : 0;
      if (now - last < iv) continue;

      await triggerWorkflow(wf.id, { scheduledAt: new Date().toISOString() });
      if (sched) {
        await db.update(forgeSchedules).set({ lastRunAt: new Date() }).where(eq(forgeSchedules.workflowId, wf.id));
      } else {
        await db.insert(forgeSchedules).values({ workflowId: wf.id, cadence: String(iv), lastRunAt: new Date(), enabled: true });
      }
      fired.push(wf.id);
    } catch (err) {
      console.warn("[cron] schedule failed for", wf.id, err);
    }
  }

  return Response.json({
    checked: scheduled.length,
    fired,
    cronFired,
    events,
    timedOut,
  });
}

export { handler as GET, handler as POST };
