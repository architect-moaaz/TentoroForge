/**
 * GET /api/presence/[route] — Spec E Wave 1.
 *
 * Server-Sent Events stream of the current viewer roster for a route.
 * The presence set is held in an in-process Map keyed by route. Users
 * heartbeat via a POST to the same URL; missing heartbeats for
 * `TTL_MS` reap the entry. Suitable for single-instance dev + demo
 * deployments; a Redis-backed impl belongs to the platform team.
 *
 * Forge runtime — do not remove.
 */
import { NextRequest } from "next/server";
import { auth } from "@/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const TTL_MS = 30_000;

type Entry = {
  userId: string;
  name?: string;
  avatarUrl?: string;
  cursor?: { x: number; y: number };
  focusedField?: string;
  lastSeen: number;
};

const g = globalThis as unknown as {
  __forgePresence?: Map<string, Map<string, Entry>>;
};
if (!g.__forgePresence) g.__forgePresence = new Map();
const rooms = g.__forgePresence;

function room(route: string): Map<string, Entry> {
  let r = rooms.get(route);
  if (!r) {
    r = new Map();
    rooms.set(route, r);
  }
  // Reap stale entries opportunistically.
  const cutoff = Date.now() - TTL_MS;
  for (const [id, e] of r) if (e.lastSeen < cutoff) r.delete(id);
  return r;
}

function serialize(r: Map<string, Entry>): string {
  const users = Array.from(r.values()).map(
    ({ lastSeen: _ls, ...rest }) => rest,
  );
  return `data: ${JSON.stringify({ users })}\n\n`;
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ route: string }> | { route: string } },
): Promise<Response> {
  const { route } = (await Promise.resolve(params)) as { route: string };
  const stream = new ReadableStream({
    start(controller) {
      const send = () => {
        try {
          controller.enqueue(new TextEncoder().encode(serialize(room(route))));
        } catch {
          /* stream closed */
        }
      };
      send();
      const tick = setInterval(send, 5_000);
      // Cleanup on cancel.
      const abort = () => {
        clearInterval(tick);
        try {
          controller.close();
        } catch {
          /* already closed */
        }
      };
      (controller as any)._abort = abort;
    },
    cancel() {
      // interval clears itself when the client disconnects.
    },
  });
  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
    },
  });
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ route: string }> | { route: string } },
): Promise<Response> {
  try {
    const session = await auth().catch(() => null);
    const { route } = (await Promise.resolve(params)) as { route: string };
    const body = (await req.json().catch(() => ({}))) as Partial<Entry>;
    const userId =
      (session?.user as any)?.id ??
      (session?.user as any)?.email ??
      body.userId ??
      "anonymous";
    const entry: Entry = {
      userId,
      name: (session?.user as any)?.name ?? body.name,
      avatarUrl: (session?.user as any)?.image ?? body.avatarUrl,
      cursor: body.cursor,
      focusedField: body.focusedField,
      lastSeen: Date.now(),
    };
    room(route).set(userId, entry);
    return Response.json({ ok: true });
  } catch (err) {
    console.error("[api/presence] POST", err);
    return Response.json({ ok: false }, { status: 500 });
  }
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ route: string }> | { route: string } },
): Promise<Response> {
  try {
    const session = await auth().catch(() => null);
    const { route } = (await Promise.resolve(params)) as { route: string };
    const userId =
      (session?.user as any)?.id ?? (session?.user as any)?.email ?? "anonymous";
    room(route).delete(userId);
    return Response.json({ ok: true });
  } catch (err) {
    console.error("[api/presence] DELETE", err);
    return Response.json({ ok: false }, { status: 500 });
  }
}
