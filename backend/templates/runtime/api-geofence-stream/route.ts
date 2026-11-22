/**
 * GET /api/geofence/stream?entity=Order — zone crossings, live.
 *
 * The open line sends first the latest crossings, then each new one:
 *
 *   data: {"id":"…","type":"geofence.entered","geofenceId":"…","entityId":"…","entityType":"Order","lat":12.97,"lng":77.64,
 *          "occurredAt":1730000000000,"detectedAt":1730000000400,"metadata":{…}}
 *
 * Who hears a crossing: only the records of that kind the app's own read rules let THIS person open — the same rule as the
 * fleet map (an admin hears every order's, a driver only their own). The list is re-read every 5 seconds, so a person who
 * loses access stops hearing. `?zone=<id>` narrows it to one zone.
 * Forge runtime — do not remove.
 */
import { visibleIds, whoIs } from "@/lib/tracking/access";
import { listen } from "@/lib/geofence/hub";
import { recentEvents } from "@/lib/geofence/store";
import type { GeofenceEvent } from "@/lib/geofence/engine";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

const HEARTBEAT_MS = 15000;
const RECHECK_MS = 5000;

export async function GET(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const entity = url.searchParams.get("entity")?.trim() ?? "";
  const zone = url.searchParams.get("zone")?.trim() || null;
  if (!(await whoIs())) return new Response("Sign in to see the zones.", { status: 401 });
  if (!entity) return new Response("entity is required", { status: 400 });
  const first = await visibleIds(entity);
  if (!first.ok) return new Response(first.error, { status: first.status });

  let seeing = first.ids;
  const encoder = new TextEncoder();
  let stop: (() => void) | null = null;
  let beat: ReturnType<typeof setInterval> | null = null;
  let recheck: ReturnType<typeof setInterval> | null = null;
  let closed = false;

  const stream = new ReadableStream({
    async start(controller) {
      const send = (text: string) => {
        if (closed) return;
        try { controller.enqueue(encoder.encode(text)); } catch { end(); }
      };
      const end = () => {
        closed = true;
        stop?.();
        if (beat) clearInterval(beat);
        if (recheck) clearInterval(recheck);
        try { controller.close(); } catch { /* already closed */ }
      };
      const hear = (e: GeofenceEvent) => {
        if (e.entityType.toLowerCase() !== entity.toLowerCase()) return;
        if (!seeing.has(e.entityId)) return;
        if (zone && e.geofenceId !== zone) return;
        send(`data: ${JSON.stringify(e)}\n\n`);
      };

      send(":connected\n\n");
      // Listen first, then read the past, so a crossing between the two is not missed (a repeat is harmless: the id is the same).
      stop = listen(hear);
      try {
        for (const e of await recentEvents(entity, [...seeing])) if (!zone || e.geofenceId === zone) send(`data: ${JSON.stringify(e)}\n\n`);
      } catch { /* an app with no geofence tables: nothing to replay */ }
      beat = setInterval(() => send(":hb\n\n"), HEARTBEAT_MS);
      recheck = setInterval(async () => {
        const again = await visibleIds(entity);
        if (!again.ok) return end();
        seeing = again.ids;
      }, RECHECK_MS);
      req.signal?.addEventListener?.("abort", end);
    },
    cancel() {
      closed = true;
      stop?.();
      if (beat) clearInterval(beat);
      if (recheck) clearInterval(recheck);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
