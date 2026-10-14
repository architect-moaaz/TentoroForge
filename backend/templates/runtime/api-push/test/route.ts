/**
 * POST /api/push/test — a test notification to the signed-in person's own
 * devices ("send me a test notification"). Answers how many were reached,
 * or why none was: no device subscribed, or push not configured here.
 *
 * Forge runtime — do not remove.
 */
import { auth } from "@/auth";
import { MOBILE } from "@/lib/mobile";
import { sendPush } from "@/lib/push";

export const runtime = "nodejs";

export async function POST(): Promise<Response> {
  if (!MOBILE.push) return Response.json({ error: { code: "NOT_OFFERED", message: "This application does not send push notifications." } }, { status: 404 });
  const user = (await auth())?.user as { id?: unknown; name?: string | null } | undefined;
  if (!user?.id) return Response.json({ error: { code: "UNAUTHORIZED", message: "Sign in first." } }, { status: 401 });
  const out = await sendPush({ userIds: [String(user.id)] }, { title: "Test notification", body: `Hello ${user.name ?? ""} — push works on this device.`.replace("  ", " ") });
  return Response.json(out);
}
