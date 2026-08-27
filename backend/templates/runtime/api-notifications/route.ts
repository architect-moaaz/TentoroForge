/**
 * GET  /api/notifications        — recent in-app notifications (workflow alerts).
 * PATCH /api/notifications { id, read } — mark one read/unread.
 * Forge runtime — do not remove.
 */
import { db } from "@/db";
import { forgeNotifications } from "@/db/schema/_forge_notifications";
import { desc, eq } from "drizzle-orm";

export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  try {
    const rows = await db.select().from(forgeNotifications).orderBy(desc(forgeNotifications.createdAt)).limit(100);
    return Response.json(rows);
  } catch (err) {
    console.error("[api/notifications] GET", err);
    return Response.json([]);
  }
}

export async function PATCH(req: Request): Promise<Response> {
  try {
    const { id, read } = await req.json();
    if (id) await db.update(forgeNotifications).set({ read: read !== false }).where(eq(forgeNotifications.id, String(id)));
    return Response.json({ ok: true });
  } catch (err) {
    console.error("[api/notifications] PATCH", err);
    return Response.json({ ok: false }, { status: 500 });
  }
}
