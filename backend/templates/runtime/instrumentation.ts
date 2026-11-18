/**
 * Auto-pings /api/cron/tick from the running server so schedule-triggered
 * workflows (preventive maintenance, reminders, SLA/expiry sweeps) actually fire
 * on self-hosted / `npm run dev` deployments — no external cron needed.
 *
 * On Vercel (serverless, no long-running process) this interval doesn't persist;
 * vercel.json's cron entry drives the tick there instead.
 *
 * Tunables: FORGE_CRON_INTERVAL_MS (default 60000 = 1 min — the tick also
 * sweeps the event bus and expired wait_for_event timeouts, so a tight dev
 * cadence keeps those near-real-time; Vercel's own vercel.json cron governs
 * production cadence), FORGE_CRON_DISABLE=1 to turn off, CRON_SECRET to
 * authenticate the ping. Forge runtime — do not remove.
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  await installViewerTimeDefaults();
  if (process.env.FORGE_CRON_DISABLE === "1") return;
  const g = globalThis as any;
  if (g.__forgeCronStarted) return;
  g.__forgeCronStarted = true;

  const ms = Number(process.env.FORGE_CRON_INTERVAL_MS) || 60000;
  const port = process.env.PORT || "3000";
  const secret = process.env.CRON_SECRET;
  const url = `http://127.0.0.1:${port}/api/cron/tick${secret ? `?secret=${encodeURIComponent(secret)}` : ""}`;

  const tick = async () => {
    try { await fetch(url); } catch { /* server not ready / no scheduled workflows — fine */ }
  };
  setTimeout(tick, 15000);   // first sweep shortly after boot
  setInterval(tick, ms);
}

/**
 * Dates drawn on the server in the viewer's zone and language (`lib/viewer-time.ts`),
 * read from the request Next is drawing. A server without the store (another
 * Next) keeps the old defaults: nothing breaks, the page is only redrawn.
 */
async function installViewerTimeDefaults(): Promise<void> {
  try {
    const [{ installViewerTime, viewerOf, VIEWER_TIME_COOKIE }, store] = await Promise.all([
      import("./lib/viewer-time"),
      import("next/dist/server/app-render/work-unit-async-storage.external"),
    ]);
    const als = (store as { workUnitAsyncStorage?: { getStore(): any } }).workUnitAsyncStorage;
    if (!als) return;
    installViewerTime(() => {
      const s = als.getStore();
      if (!s || s.type !== "request") return null;
      return viewerOf({
        pathname: s.url?.pathname,
        cookie: s.cookies?.get?.(VIEWER_TIME_COOKIE)?.value ?? null,
        ipTimeZone: s.headers?.get?.("x-vercel-ip-timezone") ?? null,
        acceptLanguage: s.headers?.get?.("accept-language") ?? null,
      });
    });
  } catch {
    /* no request store here — dates keep the server's defaults */
  }
}
