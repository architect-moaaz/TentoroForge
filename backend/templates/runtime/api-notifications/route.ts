/**
 * GET   /api/notifications                 — the signed-in person's notifications.
 * PATCH /api/notifications { id } | { all } — mark one, or all of theirs, read.
 *
 * A notification is the person's when it names them (`userId`) or, naming
 * nobody, their role. This returned EVERY row to anyone who asked, signed in
 * or not — each member could read what the app told every other member.
 * Forge runtime — do not remove.
 */
import { db } from "@/db";
import { auth } from "@/auth";
import { forgeNotifications } from "@/db/schema/_forge_notifications";
import { and, desc, eq, isNull, or, type SQL } from "drizzle-orm";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function mine(): Promise<SQL | null> {
  const user = (await auth())?.user as { id?: unknown; role?: unknown } | undefined;
  if (!user?.id) return null;
  const byUser = eq(forgeNotifications.userId, String(user.id));
  const role = user.role ? String(user.role) : "";
  return role ? (or(byUser, and(isNull(forgeNotifications.userId), eq(forgeNotifications.role, role))) as SQL) : byUser;
}

export async function GET(): Promise<Response> {
  const scope = await mine();
  if (!scope) return Response.json([], { status: 401 });
  try {
    const rows = await db.select().from(forgeNotifications).where(scope)
      .orderBy(desc(forgeNotifications.createdAt)).limit(50);
    return Response.json(rows);
  } catch (err) {
    console.error("[api/notifications] GET", err);
    return Response.json([]);
  }
}

export async function PATCH(req: Request): Promise<Response> {
  const scope = await mine();
  if (!scope) return Response.json({ ok: false }, { status: 401 });
  try {
    const { id, all, read } = await req.json();
    const where = all ? scope : id ? and(scope, eq(forgeNotifications.id, String(id))) : null;
    if (where) await db.update(forgeNotifications).set({ read: read !== false }).where(where);
    return Response.json({ ok: true });
  } catch (err) {
    console.error("[api/notifications] PATCH", err);
    return Response.json({ ok: false }, { status: 500 });
  }
}
