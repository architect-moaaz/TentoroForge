/**
 * POST /api/agent/chat — talk to one of the app's AI agents. Server-sent events.
 * GET  /api/agent/chat — the agents this person may talk to: name and look, never
 *                        the prompt, the tools or the guardrails.
 *
 * Body: { agentId?, message, conversationId?, attachments?: string[] }
 *   agentId       which agent; the app's first enabled one when omitted.
 *   attachments   forge_files ids. The model is told they exist; a tool that takes
 *                 a file (identify a product, extract a document) is how it reads them.
 *
 * Events (`data: {json}\n\n`): text · tool_call · tool_result · blocked · done · error.
 *
 * WHO IS ASKING is the session, read here and passed down as the person; the agent's
 * tools then reach the app's own routes with that same session cookie, so what an
 * agent can see and do is exactly what its user can. Forge runtime — do not remove.
 */
import { auth } from "@/auth";
import { AGENTS } from "@/agents/registry";
import { runAgent } from "@/lib/agents/runtime";
import { drizzleStore } from "@/lib/agents/store";
import { realDeps } from "@/lib/agents/io";
import type { AgentEvent, AgentRuntimeConfig, AgentUser } from "@/lib/agents/types";

/** A change the app is holding until the person agrees. Only this fact goes to the browser, never the result. */
const isHeld = (result: unknown): boolean => !!result && typeof result === "object" && (result as { held?: unknown }).held === true;

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 120;

const FILE_ID = /^[0-9a-zA-Z-]{8,64}$/;

async function sessionUser(): Promise<AgentUser | null> {
  const u = (await auth())?.user as { id?: unknown; role?: unknown; email?: unknown } | undefined;
  if (!u?.id) return null;
  return {
    id: String(u.id),
    role: u.role ? String(u.role) : undefined,
    email: u.email ? String(u.email) : undefined,
  };
}

function pickAgent(id: unknown): AgentRuntimeConfig | undefined {
  const list = (AGENTS as AgentRuntimeConfig[]).filter((a) => a.enabled);
  if (typeof id === "string" && id) return list.find((a) => a.id === id);
  return list[0];
}

export async function GET(): Promise<Response> {
  const user = await sessionUser();
  const agents = (AGENTS as AgentRuntimeConfig[])
    .filter((a) => a.enabled)
    // An agent that needs a person is not offered to a visitor.
    .filter((a) => user || !a.guardrails.input.requireAuth)
    .map((a) => ({ id: a.id, name: a.name, description: a.description ?? null, ui: a.ui }));
  return Response.json(agents);
}

export async function POST(req: Request): Promise<Response> {
  let body: any;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Expected a JSON body." }, { status: 400 });
  }
  if (typeof body?.message !== "string" || !body.message.trim()) {
    return Response.json({ error: "A message is required." }, { status: 400 });
  }
  const agent = pickAgent(body.agentId);
  if (!agent) return Response.json({ error: "No such agent." }, { status: 404 });

  const files: string[] = Array.isArray(body.attachments)
    ? body.attachments.filter((x: unknown): x is string => typeof x === "string" && FILE_ID.test(x)).slice(0, 8)
    : [];
  const message = files.length
    ? `${body.message.trim()}\n\n[Attached files (forge_files ids): ${files.join(", ")}]`
    : body.message.trim();

  const user = await sessionUser();
  const deps = await realDeps(drizzleStore);
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      const emit = (e: AgentEvent) => {
        // The browser is told THAT a tool ran and whether it worked — never what it
        // returned. The result is the model's to read; a person who may see a record
        // has the app's own pages for it, and a stream of raw rows is one more place
        // for a column to leak.
        const wire: AgentEvent =
          e.type === "tool_result"
            ? { type: "tool_result", id: e.id, tool: e.tool, ok: e.ok, error: e.error, ...(isHeld(e.result) ? { held: true } : {}) }
            : e;
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(wire)}\n\n`));
        } catch {
          /* the client went away — the run still finishes and saves */
        }
      };
      await runAgent(
        agent,
        {
          message,
          conversationId: typeof body.conversationId === "string" ? body.conversationId : null,
          user,
          cookie: req.headers.get("cookie") ?? "",
          origin: new URL(req.url).origin,
        },
        deps,
        emit,
      );
      try {
        controller.close();
      } catch {
        /* already closed */
      }
    },
  });

  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
