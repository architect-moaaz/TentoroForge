/**
 * /api/push — a device listening for the application's push notifications.
 *
 * GET answers the application's public VAPID key (what a browser subscribes
 * with) and whether push is on here; POST { subscription } records the
 * signed-in person's device; DELETE { endpoint } forgets it. The keys a
 * device sends are its own and reach only the push module.
 *
 * Forge runtime — do not remove.
 */
import { auth } from "@/auth";
import { db } from "@/db";
import { forgePushSubscriptions } from "@/db/schema/_forge_push_subscriptions";
import { eq } from "drizzle-orm";
import { MOBILE } from "@/lib/mobile";
import { publicKey, pushConfigured } from "@/lib/push";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return Response.json({ enabled: MOBILE.push === true && pushConfigured(), publicKey: MOBILE.push ? publicKey() : "" });
}

export async function POST(request: Request): Promise<Response> {
  if (!MOBILE.push) return Response.json({ error: { code: "NOT_OFFERED", message: "This application does not send push notifications." } }, { status: 404 });
  const user = (await auth())?.user as { id?: unknown } | undefined;
  if (!user?.id) return Response.json({ error: { code: "UNAUTHORIZED", message: "Sign in to subscribe." } }, { status: 401 });
  let sub: any = null;
  try { sub = (await request.json())?.subscription ?? (await Promise.resolve(null)); } catch { /* no body */ }
  const endpoint = String(sub?.endpoint ?? "");
  const p256dh = String(sub?.keys?.p256dh ?? "");
  const authKey = String(sub?.keys?.auth ?? "");
  if (!endpoint || !p256dh || !authKey) {
    return Response.json({ error: { code: "VALIDATION_ERROR", message: "A push subscription has an endpoint and keys." } }, { status: 400 });
  }
  const userAgent = request.headers.get("user-agent") ?? null;
  await db.insert(forgePushSubscriptions)
    .values({ userId: String(user.id), endpoint, p256dh, auth: authKey, userAgent } as any)
    .onConflictDoUpdate({ target: forgePushSubscriptions.endpoint, set: { userId: String(user.id), p256dh, auth: authKey, userAgent } as any });
  return Response.json({ ok: true });
}

export async function DELETE(request: Request): Promise<Response> {
  const user = (await auth())?.user as { id?: unknown } | undefined;
  if (!user?.id) return Response.json({ error: { code: "UNAUTHORIZED", message: "Sign in first." } }, { status: 401 });
  let endpoint = "";
  try { endpoint = String((await request.json())?.endpoint ?? ""); } catch { /* no body */ }
  if (!endpoint) return Response.json({ error: { code: "VALIDATION_ERROR", message: "Which device? Give its endpoint." } }, { status: 400 });
  await db.delete(forgePushSubscriptions).where(eq(forgePushSubscriptions.endpoint, endpoint));
  return Response.json({ ok: true });
}
