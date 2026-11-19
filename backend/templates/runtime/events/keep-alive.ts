/**
 * KEEP RUNNING UNTIL THIS IS DONE — on a host that stops the process once the
 * reply is sent.
 *
 * The bus processes an event right after it is written, without holding up
 * the write (events/bus.ts emitEventAndProcess). On a long-lived server that
 * work simply carries on. On Vercel the function is frozen the moment the
 * response goes out, so it never ran: on DITANS Test (wzml1sa6, 2026-11-19) a
 * recruiter moved an application, `applications.updated` was written, and the
 * stage event, the candidate's survey and everything after them waited for the
 * next cron sweep — while the same move on a local server did it all at once.
 *
 * The host's own "keep running until this is done": Vercel's request context
 * (`waitUntil`, what @vercel/functions reads), else Next's `after()`. Returns
 * whether one took the work. Never throws: outside a request (a cron tick, a
 * script) there is nothing to hand it to, and the work runs as before.
 */
export async function keepRunning(work: Promise<unknown>): Promise<boolean> {
  try {
    const ctx = (globalThis as any)[Symbol.for("@vercel/request-context")]?.get?.();
    if (typeof ctx?.waitUntil === "function") {
      ctx.waitUntil(work);
      return true;
    }
  } catch {
    /* not on Vercel */
  }
  try {
    const next: any = await import("next/server");
    const after = next.after ?? next.unstable_after;
    if (typeof after === "function") {
      after(() => work);
      return true;
    }
  } catch {
    /* no `after` here, or not inside a request */
  }
  return false;
}
