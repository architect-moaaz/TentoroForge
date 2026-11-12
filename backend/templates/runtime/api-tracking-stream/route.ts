/**
 * GET /api/tracking/stream?entity=Order&trip=<id> — the open line for ONE trip's live position.
 *
 * The customer opens it once and listens. Each time the driver's note reaches
 * the hub, it is written down this line at once (no waiting, no database poll):
 *
 *   data: {"lat":12.97,"lng":77.59,"at":1730000000000}
 *   data: {"done":true}                      the trip ended
 *
 * Only the trip asked for is sent. The existing /api/events/stream is not
 * touched and still never carries contents.
 *
 * Who may listen: anyone the app's own rules let open that trip's record (an
 * order's customer, the driver, staff who see every order), read through the
 * data engine as them. A trip they may not see is 404, the same as one that does
 * not exist. A job that is over is answered with "done" at once, no position.
 * Forge runtime — do not remove.
 */
import { jobFor, whoIs } from "@/lib/tracking/access";
import { finished, tripKey } from "@/lib/tracking/rules";
import { latest, listen } from "@/lib/tracking/hub";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

const HEARTBEAT_MS = 15000;

export async function GET(req: Request): Promise<Response> {
  const params = new URL(req.url).searchParams;
  const entity = params.get("entity")?.trim() ?? "";
  const id = params.get("trip")?.trim() ?? "";
  if (!(await whoIs())) return new Response("Sign in to follow a trip.", { status: 401 });
  if (!entity || !id) return new Response("entity and trip are required", { status: 400 });
  const found = await jobFor(entity, id);
  if (!found.ok) return new Response(found.error, { status: found.status });
  const trip = tripKey(entity, id);
  const over = finished(found.job);

  // A PHONE CANNOT HOLD THE OPEN LINE (its fetch does not stream), so it asks for the newest note instead, every few
  // seconds: `?snapshot=1` answers once, with the same access checks as above, and the line is not opened.
  if (params.get("snapshot") === "1") {
    return Response.json({ position: over ? null : (latest(trip) ?? null), done: over }, { headers: { "cache-control": "no-store" } });
  }

  const encoder = new TextEncoder();
  let stop: (() => void) | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;
  let closed = false;

  const stream = new ReadableStream({
    start(controller) {
      const send = (text: string) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(text));
        } catch {
          end();
        }
      };
      const end = () => {
        closed = true;
        stop?.();
        if (timer) clearInterval(timer);
        try { controller.close(); } catch { /* already closed */ }
      };

      send(":connected\n\n");
      if (over) {
        // A finished job: say so and close. No position is shown after it.
        send(`data: ${JSON.stringify({ done: true })}\n\n`);
        end();
        return;
      }
      // Someone who opens late still sees where the driver is right now.
      const now = latest(trip);
      if (now) send(`data: ${JSON.stringify(now)}\n\n`);

      stop = listen(trip, (f) => {
        send(`data: ${JSON.stringify(f)}\n\n`);
        if ("done" in f) end(); // the trip is over: close the line
      });
      timer = setInterval(() => send(":hb\n\n"), HEARTBEAT_MS);
      req.signal?.addEventListener?.("abort", end);
    },
    cancel() {
      closed = true;
      stop?.();
      if (timer) clearInterval(timer);
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
