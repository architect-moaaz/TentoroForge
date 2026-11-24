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
 * Every frame carries `id:` — the watermark, the last event's own
 * `created_at` as the database wrote it. On platforms that cap function
 * duration the stream ends at maxDuration; EventSource reconnects with that id
 * as Last-Event-ID (a tab coming back from hidden passes it as ?since=), and
 * the stream carries on from it: nothing missed, nothing sent twice, and the
 * client never reloads a page "in case".
 *
 * THE WATERMARK IS THE DATABASE'S OWN TEXT. It was a JS Date: microseconds
 * cut to milliseconds, so `created_at > since` matched the newest event again
 * on every poll and every open tab re-fetched its page every three seconds,
 * hidden or not, for ever — 5.85 GB out of DITANS's Test database in six days
 * (2026-11-24). And `created_at` has no zone: read into a Date it took the
 * server's own, and on a machine east of UTC the watermark jumped hours back.
 * Compared as text cast to `timestamp`, neither can happen.
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

/** A watermark as the stream writes it: a `timestamp` in Postgres's own text. */
const WATERMARK = /^\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(\.\d{1,6})?$/;

export async function GET(req: Request): Promise<Response> {
  const encoder = new TextEncoder();
  const asked = req.headers.get("last-event-id") || new URL(req.url).searchParams.get("since") || "";
  let since: string | null = WATERMARK.test(asked) ? asked : null;
  let closed = false;
  let timer: ReturnType<typeof setInterval> | null = null;

  const stream = new ReadableStream({
    async start(controller) {
      const send = (text: string) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(text));
        } catch {
          closed = true;
          if (timer) clearInterval(timer);
        }
      };

      // A first visit starts at the tail: what is already there was in the
      // page this tab was given.
      if (since === null) {
        try {
          const res: any = await db.execute(sql`
            SELECT COALESCE(max(created_at), localtimestamp)::text AS at FROM forge_events
          `);
          since = String(_rows(res)[0]?.at ?? "") || null;
        } catch {
          since = null; // table missing (older app) — the polls below say nothing
        }
      }

      const poll = async () => {
        if (closed || since === null) {
          send(":hb\n\n");
          return;
        }
        try {
          const res: any = await db.execute(sql`
            SELECT type, entity, entity_id, created_at::text AS at
            FROM forge_events
            WHERE created_at > ${since}::timestamp
            ORDER BY created_at
            LIMIT 200
          `);
          const rows = _rows(res);
          if (rows.length) {
            since = String(rows[rows.length - 1].at);
            const events = rows.map((r) => ({
              type: String(r.type),
              entity: r.entity ?? null,
              entityId: r.entity_id ?? null,
              createdAt: r.at,
            }));
            send(`id: ${since}\ndata: ${JSON.stringify({ events })}\n\n`);
          } else {
            send(":hb\n\n");
          }
        } catch {
          // DB hiccup — keep the socket alive; the client's behaviour
          // degrades to exactly what it was before this stream existed.
          send(":hb\n\n");
        }
      };

      // The watermark goes out at once, so a tab that hears no event still
      // knows where to carry on from.
      send(since === null ? ":connected\n\n" : `id: ${since}\ndata: {"events":[]}\n\n`);
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
