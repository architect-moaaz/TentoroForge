/**
 * The builder's live run. Forge runtime — do not remove.
 *
 * GET  /api/agent/debug                   — is debug on here? (agents, and whether it is development)
 * GET  /api/agent/debug?users=1           — the app's people, to pick who to run as
 * POST /api/agent/debug { message, sessionId, asUserId, allowChanges?, config? }
 *                                         — one chat message as that person, streamed step by step
 *
 * THIS SEES WHAT A CUSTOMER'S CHAT DELIBERATELY HIDES (every tool's full result, the model's prompt), and it can
 * act as any user, so it is shut unless ALL of these hold: the app is not in production, the platform's secret
 * file `.forge-debug-secret` exists in the app folder, and the request carries that secret. Anything else is a
 * plain 404, as if the route did not exist. The platform (never the browser) holds the secret and proxies.
 */
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { AGENTS } from "@/agents/registry";
import { db } from "@/db";
import { debugDeps, describeAgent, sameSecret, sessionStore, wireResult, type DebugEvent } from "@/lib/agents/debug";
import { realDeps } from "@/lib/agents/io";
import { runAgent } from "@/lib/agents/runtime";
import type { AgentEvent, AgentRuntimeConfig } from "@/lib/agents/types";
import { sql } from "drizzle-orm";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

const NOT_FOUND = () => Response.json({ error: "Not found." }, { status: 404 });

/** `null` when the request may use debug; otherwise the response to give. */
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

type Row = Record<string, unknown>;

async function userRows(where: ReturnType<typeof sql> | null): Promise<Row[]> {
  const res: any = await (db as any).execute(where ? sql`SELECT * FROM users WHERE ${where} LIMIT 1` : sql`SELECT * FROM users LIMIT 300`);
  return Array.isArray(res) ? res : (res?.rows ?? []);
}

const roleOf = (r: Row): string | null => (r.role ?? r.account_type ?? null) as string | null;
const nameOf = (r: Row): string => String(r.display_name ?? r.name ?? r.full_name ?? r.email ?? r.id);

/** What the sign-in puts in the session beyond id, email, name and role: every scalar column but the credential. */
function profileOf(row: Row): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(row)) {
    if (["password", "password_hash", "passwordHash", "id", "email", "name", "role", "account_type", "accountType"].includes(k)) continue;
    if (v === null || ["string", "number", "boolean"].includes(typeof v)) out[k] = v;
  }
  return out;
}

/** A session cookie for this person, minted the way the app's own sign-in would, so the app's routes decide what
 *  they may see and do. */
async function sessionCookieFor(row: Row): Promise<string> {
  const { encode } = await import("next-auth/jwt");
  const { sessionCookieName } = await import("@/lib/session-cookie");
  const token = {
    sub: String(row.id),
    id: String(row.id),
    email: row.email ?? null,
    name: nameOf(row),
    role: roleOf(row) ?? "user",
    accountType: (row.account_type as string | null) ?? null,
    profile: profileOf(row),
  };
  const jwt = await encode({ token, secret: process.env.NEXTAUTH_SECRET || "dev-secret", maxAge: 60 * 60 });
  return `${sessionCookieName()}=${jwt}`;
}

export async function GET(req: Request): Promise<Response> {
  const no = await refuse(req);
  if (no) return no;
  const url = new URL(req.url);
  if (url.searchParams.get("users")) {
    try {
      const rows = await userRows(null);
      return Response.json({
        users: rows
          .filter((r) => r.is_active !== false)
          .map((r) => ({ id: String(r.id), name: nameOf(r), email: (r.email as string | null) ?? null, role: roleOf(r) })),
      });
    } catch {
      return Response.json({ users: [], note: "The app's people could not be listed." });
    }
  }
  return Response.json({
    debug: true,
    agents: (AGENTS as AgentRuntimeConfig[]).map((a) => ({ id: a.id, name: a.name, enabled: a.enabled })),
  });
}

export async function POST(req: Request): Promise<Response> {
  const no = await refuse(req);
  if (no) return no;

  let body: any;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Expected a JSON body." }, { status: 400 });
  }
  const message = typeof body?.message === "string" ? body.message.trim() : "";
  if (!message) return Response.json({ error: "A message is required." }, { status: 400 });
  if (typeof body?.asUserId !== "string" || !body.asUserId) return Response.json({ error: "Choose who to run as." }, { status: 400 });

  // The draft the builder is working on, or the agent as installed.
  const draft = body.config && typeof body.config === "object" && Array.isArray(body.config.tools) && typeof body.config.systemPrompt === "string";
  const list = AGENTS as AgentRuntimeConfig[];
  const config: AgentRuntimeConfig | undefined = draft
    ? ({ ...body.config, enabled: true } as AgentRuntimeConfig)
    : (typeof body.agentId === "string" ? list.find((a) => a.id === body.agentId) : list[0]);
  if (!config) return Response.json({ error: "That agent is not installed in this app yet. Apply it first, or run the draft." }, { status: 404 });

  let who: Row | undefined;
  try {
    who = (await userRows(sql`id::text = ${body.asUserId}`))[0];
  } catch {
    /* handled below */
  }
  if (!who) return Response.json({ error: "No such person in this app." }, { status: 404 });
  let cookie: string;
  try {
    cookie = await sessionCookieFor(who);
  } catch (e) {
    return Response.json({ error: `Could not sign in as that person (${e instanceof Error ? e.message : String(e)}).` }, { status: 500 });
  }

  const sessionId = typeof body.sessionId === "string" && body.sessionId ? body.sessionId : randomUUID();
  const store = sessionStore(sessionId);
  const allowChanges = body.allowChanges === true;
  const encoder = new TextEncoder();
  const t0 = Date.now();

  const stream = new ReadableStream({
    async start(controller) {
      const send = (e: AgentEvent | DebugEvent) => {
        let wire: Record<string, unknown> = { ...e, t: Date.now() - t0 };
        if (e.type === "tool_result") wire = { ...wire, ...wireResult((e as { result?: unknown }).result) };
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(wire)}\n\n`));
        } catch {
          /* the screen went away */
        }
      };
      try {
        send({
          type: "debug_start",
          agent: describeAgent(config),
          user: { id: String(who!.id), name: nameOf(who!), email: who!.email ?? null, role: roleOf(who!) },
          allowChanges,
          draft: !!draft,
        });
        const deps = debugDeps(await realDeps(store), send, { allowChanges });
        await runAgent(
          config,
          {
            message,
            conversationId: typeof body.conversationId === "string" ? body.conversationId : null,
            user: { id: String(who!.id), role: roleOf(who!) ?? undefined, email: who!.email ? String(who!.email) : undefined },
            cookie,
            origin: new URL(req.url).origin,
          },
          deps,
          send,
        );
      } catch (e) {
        send({ type: "error", message: e instanceof Error ? e.message : String(e) });
      }
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
      "x-forge-debug-session": sessionId,
    },
  });
}
