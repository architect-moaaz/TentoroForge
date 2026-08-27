/**
 * Auto-pings /api/cron/tick from the running server so schedule-triggered
 * workflows (preventive maintenance, reminders, SLA/expiry sweeps) actually fire
 * on self-hosted / `npm run dev` deployments — no external cron needed.
 *
 * On Vercel (serverless, no long-running process) this interval doesn't persist;
 * vercel.json's cron entry drives the tick there instead.
 *
 * Tunables: FORGE_CRON_INTERVAL_MS (default 300000 = 5 min), FORGE_CRON_DISABLE=1
 * to turn off, CRON_SECRET to authenticate the ping. Forge runtime — do not remove.
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  if (process.env.FORGE_CRON_DISABLE === "1") return;
  const g = globalThis as any;
  if (g.__forgeCronStarted) return;
  g.__forgeCronStarted = true;

  const ms = Number(process.env.FORGE_CRON_INTERVAL_MS) || 300000;
  const port = process.env.PORT || "3000";
  const secret = process.env.CRON_SECRET;
  const url = `http://127.0.0.1:${port}/api/cron/tick${secret ? `?secret=${encodeURIComponent(secret)}` : ""}`;

  const tick = async () => {
    try { await fetch(url); } catch { /* server not ready / no scheduled workflows — fine */ }
  };
  setTimeout(tick, 15000);   // first sweep shortly after boot
  setInterval(tick, ms);
}
