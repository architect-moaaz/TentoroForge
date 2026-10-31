/**
 * POST /api/agent/feedback — the thumbs up / thumbs down under an assistant answer.
 *
 * Body: { conversationId, messageId, rating: 1 | -1, note? }
 *   messageId   the saved assistant message (the chat's `done` event carries it).
 *   note        optional, a line on what went wrong (kept to 300 characters).
 *
 * Only the person who owns the conversation may rate in it: someone else's conversation is a plain 404, the same as one
 * that does not exist. Rating again replaces the earlier rating, so it is safe to send twice. Forge runtime — do not remove.
 */
import { auth } from "@/auth";
import { drizzleStore } from "@/lib/agents/store";
import { rateTurn } from "@/lib/agents/turns-store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_NOTE = 300;
const MAX_ID = 64;

export async function POST(req: Request): Promise<Response> {
  const user = (await auth())?.user as { id?: unknown } | undefined;
  if (!user?.id) return Response.json({ error: "Sign in to rate an answer." }, { status: 401 });
  const userId = String(user.id);

  let body: any;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Expected a JSON body." }, { status: 400 });
  }
  const conversationId = typeof body?.conversationId === "string" ? body.conversationId.trim() : "";
  const messageId = typeof body?.messageId === "string" ? body.messageId.trim() : "";
  if (!conversationId || conversationId.length > MAX_ID) {
    return Response.json({ error: "Say which conversation the answer is in." }, { status: 400 });
  }
  if (!messageId || messageId.length > MAX_ID) {
    return Response.json({ error: "Say which answer you are rating." }, { status: 400 });
  }
  if (body.rating !== 1 && body.rating !== -1) {
    return Response.json({ error: "The rating must be 1 (good) or -1 (bad)." }, { status: 400 });
  }
  if (body.note != null && typeof body.note !== "string") {
    return Response.json({ error: "The note must be text." }, { status: 400 });
  }
  const note = typeof body.note === "string" && body.note.trim() ? body.note.trim().slice(0, MAX_NOTE) : null;

  try {
    const mine = await drizzleStore.getConversation(conversationId, userId);
    if (!mine) return Response.json({ error: "No such conversation." }, { status: 404 });
    const updated = await rateTurn({ conversationId, messageId, rating: body.rating, note });
    if (!updated) return Response.json({ error: "That answer was not recorded, so it cannot be rated." }, { status: 404 });
    return Response.json({ ok: true, rating: body.rating });
  } catch (err) {
    console.error("[api/agent/feedback]", err);
    return Response.json({ error: "Could not save your rating." }, { status: 500 });
  }
}
