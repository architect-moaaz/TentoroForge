/**
 * GET  /api/agent/handoffs?conversation=<id>   — the signed-in person's OWN handoff for one of their conversations.
 * GET  /api/agent/handoffs                     — the inbox: ?status=active (default) | resolved | all. Handlers only.
 * GET  /api/agent/handoffs?id=<uuid>           — one handoff with its conversation. Handlers only.
 * POST /api/agent/handoffs { id, action }      — claim | release | resolve (+ note) | assign (+ assigneeId, assigneeName)
 *                                                  | reply (+ text): write to the person in their own chat. An unclaimed
 *                                                  handoff is claimed by whoever replies; one someone else holds is not.
 *
 * "Handlers" are the people the agent's human-handoff settings name (by role or by person); with nobody named,
 * any signed-in person. A person never reads anyone else's handoff, and a handler only the agents they handle.
 * Forge runtime — do not remove.
 */
import { auth } from "@/auth";
import { AGENTS } from "@/agents/registry";
import { canHandle } from "@/lib/agents/handoff";
import { changeHandoff, getHandoff, handoffForConversation, listHandoffs, sendReply, teamWrote, transcript } from "@/lib/agents/handoff-store";
import { drizzleStore } from "@/lib/agents/store";
import type { AgentUser, HandoffRecord } from "@/lib/agents/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Me = AgentUser & { name?: string | null };

async function me(): Promise<Me | null> {
  const u = (await auth())?.user as Record<string, unknown> | undefined;
  if (!u?.id) return null;
  return {
    id: String(u.id),
    role: u.role ? String(u.role) : undefined,
    email: u.email ? String(u.email) : undefined,
    name: (u.displayName ?? u.name ?? u.email ?? null) as string | null,
  };
}

const specFor = (agentId: string) => AGENTS.find((a) => a.id === agentId)?.handoff ?? null;
const handles = (user: Me, h: HandoffRecord) => canHandle(specFor(h.agentId), user);
const handlesAny = (user: Me) => AGENTS.some((a) => a.handoff && canHandle(a.handoff, user));

const FORBIDDEN = { error: "Only the people who handle handoffs can use the inbox." };

export async function GET(req: Request): Promise<Response> {
  const user = await me();
  if (!user) return Response.json({ error: "Sign in first." }, { status: 401 });
  const url = new URL(req.url);
  try {
    // A person's own: is my conversation with a person, and where does it stand?
    const conversation = url.searchParams.get("conversation");
    if (conversation) {
      const mine = await drizzleStore.getConversation(conversation, user.id);
      if (!mine) return Response.json({ handoff: null });
      const h = await handoffForConversation(conversation);
      return Response.json({
        handoff: h
          ? { ref: h.ref, status: h.status, assignedToName: h.assignedToName ?? null, resolutionNote: h.resolutionNote ?? null }
          : null,
      });
    }

    if (!handlesAny(user)) return Response.json(FORBIDDEN, { status: 403 });

    const id = url.searchParams.get("id");
    if (id) {
      const h = await getHandoff(id);
      if (!h || !handles(user, h)) return Response.json({ error: "No such handoff." }, { status: 404 });
      return Response.json({ handoff: h, messages: await transcript(h.conversationId), me: user });
    }

    const status = url.searchParams.get("status");
    const rows = await listHandoffs({ status: status === "resolved" || status === "all" ? status : "active" });
    return Response.json({ handoffs: rows.filter((h) => handles(user, h)), me: user });
  } catch (err) {
    console.error("[api/agent/handoffs] GET", err);
    return Response.json(
      { error: "Handoffs are not set up in this app yet. It needs a database update (npx drizzle-kit push)." },
      { status: 500 },
    );
  }
}

export async function POST(req: Request): Promise<Response> {
  const user = await me();
  if (!user) return Response.json({ error: "Sign in first." }, { status: 401 });
  let body: any;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Expected a JSON body." }, { status: 400 });
  }
  try {
    const current = typeof body?.id === "string" ? await getHandoff(body.id) : null;
    if (!current || !handles(user, current)) return Response.json({ error: "No such handoff." }, { status: 404 });

    if (body.action === "reply") {
      const text = typeof body.text === "string" ? body.text.trim().slice(0, 4000) : "";
      if (!text) return Response.json({ error: "Write something to send." }, { status: 400 });
      if (current.status === "resolved") return Response.json({ error: "This one is resolved. The person is back with the assistant." }, { status: 409 });
      if (current.status === "claimed" && current.assignedToId !== user.id) {
        return Response.json({ error: `${current.assignedToName ?? "Someone else"} has this one. Take it over first.` }, { status: 409 });
      }
      const held = current.status === "claimed" ? current : await changeHandoff(current.id, { action: "claim", by: { id: user.id, name: user.name } });
      if (!held) return Response.json({ error: "That is not possible: it may already be resolved." }, { status: 409 });
      await sendReply(held, text);
      await teamWrote(held, text).catch(() => {});
      return Response.json({ handoff: held });
    }

    let change;
    switch (body.action) {
      case "claim":
        change = { action: "claim" as const, by: { id: user.id, name: user.name } };
        break;
      case "release":
        change = { action: "release" as const };
        break;
      case "resolve":
        change = { action: "resolve" as const, note: typeof body.note === "string" ? body.note : "" };
        break;
      case "assign":
        if (typeof body.assigneeId !== "string" || !body.assigneeId) {
          return Response.json({ error: "Say who to assign it to." }, { status: 400 });
        }
        change = { action: "assign" as const, to: { id: body.assigneeId, name: typeof body.assigneeName === "string" ? body.assigneeName : null } };
        break;
      default:
        return Response.json({ error: "Unknown action." }, { status: 400 });
    }
    const next = await changeHandoff(current.id, change);
    if (!next) return Response.json({ error: "That is not possible: it may already be resolved." }, { status: 409 });
    return Response.json({ handoff: next });
  } catch (err) {
    console.error("[api/agent/handoffs] POST", err);
    return Response.json({ error: "Could not update the handoff." }, { status: 500 });
  }
}
