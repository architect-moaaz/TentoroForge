/**
 * Watching the app's real chats live. Forge runtime — do not remove.
 *
 * GET /api/agent/debug             — is watching possible here? (the agents the app has)
 * GET /api/agent/debug?watch=1     — every chat the app has, as it happens: who wrote what, each step the runtime
 *                                    takes, each model call, each tool and the real request behind it (a stream)
 *                                    &role=Admin   only the chats of people holding that role
 *                                    &user=<id>    only one person's chats (the app's own id for them)
 *
 * THIS SEES WHAT A CUSTOMER'S CHAT DELIBERATELY HIDES (every tool's full result), so it is shut unless ALL of these
 * hold: the app is not in production, the platform's secret file `.forge-debug-secret` exists in the app folder, and
 * the request carries that secret. Anything else is a plain 404, as if the route did not exist. The platform (never
 * the browser) holds the secret and proxies. It can only WATCH: there is no way in here to make the assistant do
 * anything.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";
import { AGENTS } from "@/agents/registry";
import { sameSecret } from "@/lib/agents/debug";
import type { AgentRuntimeConfig } from "@/lib/agents/types";
import { subscribe, type WatchFilter } from "@/lib/agents/watch";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const NOT_FOUND = () => Response.json({ error: "Not found." }, { status: 404 });

/** `null` when the request may use this; otherwise the response to give. */
async function refuse(req: Request): Promise<Response | null> {
  if (process.env.NODE_ENV === "production") return NOT_FOUND();
  let secret = "";
  try {
    secret = (await readFile(path.join(process.cwd(), ".forge-debug-secret"), "utf8")).trim();
  } catch {
    return NOT_FOUND();
  }
  return sameSecret(secret, req.headers.get("x-forge-debug-secret") ?? "") ? null : NOT_FOUND();
}

/** The chats of everyone, or only of one role or one person: what the builder's live flowchart is drawn from. */
function watchStream(req: Request, filter: WatchFilter): Response {
  const encoder = new TextEncoder();
  let stop: (() => void) | null = null;
  let beat: ReturnType<typeof setInterval> | null = null;
  const stream = new ReadableStream({
    start(controller) {
      const write = (text: string) => {
        try {
          controller.enqueue(encoder.encode(text));
        } catch {
          /* the watcher went away */
        }
      };
      write(`data: ${JSON.stringify({ type: "watch_ready", agents: (AGENTS as AgentRuntimeConfig[]).map((a) => ({ id: a.id, name: a.name })), filter })}\n\n`);
      stop = subscribe((e) => write(`data: ${JSON.stringify(e)}\n\n`), filter);
      // A quiet connection is kept open (and proven alive) with a comment every so often.
      beat = setInterval(() => write(": ping\n\n"), 15_000);
      req.signal.addEventListener("abort", () => cleanup());
    },
    cancel() {
      cleanup();
    },
  });
  function cleanup() {
    if (beat) clearInterval(beat);
    beat = null;
    stop?.();
    stop = null;
  }
  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}

export async function GET(req: Request): Promise<Response> {
  const no = await refuse(req);
  if (no) return no;
  const url = new URL(req.url);
  if (url.searchParams.get("watch")) {
    const role = url.searchParams.get("role")?.trim();
    const userId = url.searchParams.get("user")?.trim();
    return watchStream(req, { ...(role ? { role } : {}), ...(userId ? { userId } : {}) });
  }
  return Response.json({
    debug: true,
    agents: (AGENTS as AgentRuntimeConfig[]).map((a) => ({ id: a.id, name: a.name, enabled: a.enabled })),
  });
}
