/**
 * GET /api/events/stream — Server-Sent Events tail of the forge_events bus.
 *
 * The live-UI half of the eventing layer (R3): pages subscribe via
 * LiveRefresh (src/lib/LiveRefresh.tsx) and re-fetch their server data the
 * moment an event lands for one of their entities, instead of polling on a
 * timer. The stream itself polls Postgres server-side (~2.5s) — one cheap
 * indexed query fanned out to every subscriber — so the client contract is
 * push even though the store is pulled. No LISTEN/NOTIFY daemon (serverless).
 *
 * Wire format (one JSON frame per poll that found rows):
 *   data: {"events":[{"type":"orders.created","entity":"orders",
 *                     "entityId":"…","createdAt":"…"}]}
 * Payloads are intentionally NOT forwarded — the page re-fetches through its
 * own auth-gated data path; the stream only says WHAT changed, never what
 * the change contained. A ":hb" comment heartbeat rides every empty poll so
 * proxies keep the socket open.
 *
 * On platforms that cap function duration the stream ends at maxDuration;
 * EventSource auto-reconnects and the `since` watermark restarts at connect
 * time (missed intervals are covered by the client's refresh-on-reconnect).
 * Forge runtime — do not remove.
 */
import { db } from "@/db";
import { sql } from "drizzle-orm";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

const POLL_MS = 2500;

function _rows(res: unknown): any[] {
  return Array.isArray(res) ? res : ((res as { rows?: any[] })?.rows ?? []);
}

export async function GET(req: Request): Promise<Response> {
  const encoder = new TextEncoder();
  let since = new Date();
  let closed = false;
  let timer: ReturnType<typeof setInterval> | null = null;

  const stream = new ReadableStream({
    start(controller) {
      const send = (text: string) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(text));
        } catch {
          closed = true;
          if (timer) clearInterval(timer);
        }
      };

      const poll = async () => {
        if (closed) return;
        try {
          const res: any = await db.execute(sql`
            SELECT type, entity, entity_id, created_at
            FROM forge_events
            WHERE created_at > ${since.toISOString()}::timestamptz
            ORDER BY created_at
            LIMIT 200
          `);
          const rows = _rows(res);
          if (rows.length) {
            const last = rows[rows.length - 1];
            since = new Date(last.created_at);
            const events = rows.map((r) => ({
              type: String(r.type),
              entity: r.entity ?? null,
              entityId: r.entity_id ?? null,
              createdAt: r.created_at,
            }));
            send(`data: ${JSON.stringify({ events })}\n\n`);
          } else {
            send(":hb\n\n");
          }
        } catch {
          // Table missing (older app) / DB hiccup — keep the socket alive;
          // the client's behavior degrades to exactly what it was before
          // this stream existed (no live refresh).
          send(":hb\n\n");
        }
      };

      send(":connected\n\n");
      timer = setInterval(() => void poll(), POLL_MS);
      req.signal?.addEventListener?.("abort", () => {
        closed = true;
        if (timer) clearInterval(timer);
        try {
          controller.close();
        } catch {
          /* already closed */
        }
      });
    },
    cancel() {
      closed = true;
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
