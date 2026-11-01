/**
 * GET|POST /api/cron/insights — the catch-up for the platform's insights. Called by /api/cron/tick every time it runs.
 *
 * Every assistant turn is sent to the platform right after it happens. A turn that could not be sent (the platform
 * was down, the app crashed, the process froze) is still in the app's database, marked "not sent". Here the oldest of
 * those are sent, in batches, and turns that were sent more than a week ago are deleted so the table does not grow
 * for ever. An app that is not connected to the platform does neither: this answers `{ configured: false }`.
 *
 * It sits under /api/cron/ so the app's sign-in gate lets it through, and it is guarded like the tick: with
 * CRON_SECRET set, the request must carry it (Bearer header or ?secret=). The answer holds counts only.
 * Forge runtime — do not remove.
 */
import { runInsightsTick } from "@/lib/agents/insights-outbox";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

async function handler(req: Request): Promise<Response> {
  // Read the same way the tick reads it, so a secret set under /settings/integrations works here too.
  let secret: string | undefined;
  try {
    const { getSecret } = await import("@/lib/integrations/resolver");
    secret = await getSecret("cron", "CRON_SECRET");
  } catch {
    secret = process.env.CRON_SECRET;
  }
  if (secret) {
    const auth = req.headers.get("authorization") || "";
    const qs = new URL(req.url).searchParams.get("secret");
    if (auth !== `Bearer ${secret}` && qs !== secret) return new Response("Unauthorized", { status: 401 });
  }
  try {
    return Response.json(await runInsightsTick());
  } catch (err) {
    console.warn("[cron/insights]", err);
    return Response.json({ error: "Could not run the insights catch-up." }, { status: 500 });
  }
}

export { handler as GET, handler as POST };
