/**
 * /api/push/device — a PHONE listening for the application's alerts.
 *
 * POST { token, platform? } records the signed-in person's phone (the Expo push token the native app was given);
 * DELETE { token } forgets it (signing out, or switching the alerts off). A token that already belongs to someone else
 * moves to the person who sent it: one phone, one person at a time.
 *
 * Forge runtime — do not remove.
 */
import { auth } from "@/auth";
import { db } from "@/db";
import { forgeDeviceTokens } from "@/db/schema/_forge_device_tokens";
import { and, eq } from "drizzle-orm";
import { MOBILE } from "@/lib/mobile";
import { validExpoToken } from "@/lib/expo-push";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function bodyOf(request: Request): Promise<any> {
  try { return await request.json(); } catch { return {}; }
}

export async function POST(request: Request): Promise<Response> {
  if (!MOBILE.push) return Response.json({ error: { code: "NOT_OFFERED", message: "This application does not send push notifications." } }, { status: 404 });
  const user = (await auth())?.user as { id?: unknown } | undefined;
  if (!user?.id) return Response.json({ error: { code: "UNAUTHORIZED", message: "Sign in to get alerts on this phone." } }, { status: 401 });
  const body = await bodyOf(request);
  const token = String(body?.token ?? "");
  if (!validExpoToken(token)) {
    return Response.json({ error: { code: "VALIDATION_ERROR", message: "A phone's push token looks like ExponentPushToken[...]." } }, { status: 400 });
  }
  const platform = ["ios", "android"].includes(String(body?.platform)) ? String(body.platform) : null;
  await db.insert(forgeDeviceTokens)
    .values({ userId: String(user.id), token, platform } as any)
    .onConflictDoUpdate({ target: forgeDeviceTokens.token, set: { userId: String(user.id), platform, updatedAt: new Date() } as any });
  return Response.json({ ok: true });
}

export async function DELETE(request: Request): Promise<Response> {
  const user = (await auth())?.user as { id?: unknown } | undefined;
  if (!user?.id) return Response.json({ error: { code: "UNAUTHORIZED", message: "Sign in first." } }, { status: 401 });
  const token = String((await bodyOf(request))?.token ?? "");
  if (!token) return Response.json({ error: { code: "VALIDATION_ERROR", message: "Which phone? Give its token." } }, { status: 400 });
  // only the person the phone is registered to may forget it
  await db.delete(forgeDeviceTokens).where(and(eq(forgeDeviceTokens.token, token), eq(forgeDeviceTokens.userId, String(user.id))));
  return Response.json({ ok: true });
}
