/**
 * GET /api/agent/conversations?agent=<id>   — the signed-in person's conversations
 *                                             with that agent, newest first.
 * GET /api/agent/conversations?id=<uuid>    — one of them, with its messages.
 *
 * Only ever the caller's own: the store reads a conversation back for the person
 * who started it and no one else. Forge runtime — do not remove.
 */
import { auth } from "@/auth";
import { listConversations, readConversation } from "@/lib/agents/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  const user = (await auth())?.user as { id?: unknown } | undefined;
  if (!user?.id) return Response.json({ error: "Sign in to see your conversations." }, { status: 401 });
  const userId = String(user.id);
  const url = new URL(req.url);
  try {
    const id = url.searchParams.get("id");
    if (id) {
      const conv = await readConversation(id, userId);
      return conv ? Response.json(conv) : Response.json({ error: "No such conversation." }, { status: 404 });
    }
    const agent = url.searchParams.get("agent") ?? "";
    return Response.json(await listConversations(agent, userId));
  } catch (err) {
    console.error("[api/agent/conversations]", err);
    return Response.json({ error: "Could not read conversations." }, { status: 500 });
  }
}
