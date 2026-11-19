/**
 * GET /api/tracking/fleet?entity=Driver — every person on duty, on one map.
 *
 * The open line sends first the people on duty right now, then each change:
 *
 *   data: {"id":"…","lat":12.97,"lng":77.59,"at":1730000000000,"label":"Asha","kind":"Sedan"}
 *   data: {"gone":"<id>"}                  that person went off duty or went quiet
 *
 * Who is shown: only the records the app's own read rules let THIS person open
 * (an admin sees every driver; a driver sees only themselves). The list is
 * re-read every 5 seconds: a person who loses access stops being shown, and a
 * person whose record says they are no longer on duty (offline, suspended) is
 * taken off the map without waiting for their phone to say so.
 * Forge runtime — do not remove.
 */
import { visibleMembers, whoIs } from "@/lib/tracking/access";
import { fleetKey, whyNotOnDuty } from "@/lib/tracking/rules";
import { fleetDrop, fleetListen, fleetSnapshot, type FleetFrame } from "@/lib/tracking/hub";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

const HEARTBEAT_MS = 15000;
const RECHECK_MS = 5000;

export async function GET(req: Request): Promise<Response> {
  const entity = new URL(req.url).searchParams.get("entity")?.trim() ?? "";
  if (!(await whoIs())) return new Response("Sign in to see the map.", { status: 401 });
  if (!entity) return new Response("entity is required", { status: 400 });
  const first = await visibleMembers(entity);
  if (!first.ok) return new Response(first.error, { status: first.status });

  const key = fleetKey(entity);
  let seeing = new Set(first.rows.keys());
  const encoder = new TextEncoder();
  let stop: (() => void) | null = null;
  let beat: ReturnType<typeof setInterval> | null = null;
  let recheck: ReturnType<typeof setInterval> | null = null;
  let closed = false;

  const stream = new ReadableStream({
    start(controller) {
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
      const out = (f: FleetFrame) => {
        const id = "gone" in f ? f.gone : f.id;
        if (seeing.has(id)) send(`data: ${JSON.stringify(f)}\n\n`);
      };

      send(":connected\n\n");
      for (const m of fleetSnapshot(key)) out(m);
      stop = fleetListen(key, out);
      beat = setInterval(() => send(":hb\n\n"), HEARTBEAT_MS);
      recheck = setInterval(async () => {
        const again = await visibleMembers(entity);
        if (!again.ok) return end();
        for (const id of seeing) if (!again.rows.has(id)) send(`data: ${JSON.stringify({ gone: id })}\n\n`);
        const before = seeing;
        seeing = new Set(again.rows.keys());
        // WHAT THE RECORD SAYS WINS OVER THE LAST NOTE. A driver who pressed
        // "Go offline" (a workflow, not this line) would otherwise stay a pin
        // until their phone went quiet for two minutes.
        for (const m of fleetSnapshot(key)) {
          const row = again.rows.get(m.id);
          if (row && whyNotOnDuty(row)) fleetDrop(key, m.id);
        }
        // Someone newly visible who is already on the map appears at once.
        for (const m of fleetSnapshot(key)) if (seeing.has(m.id) && !before.has(m.id)) out(m);
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
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
