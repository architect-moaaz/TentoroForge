/**
 * Where the signed-in person is signed in, and signing the others out.
 *
 * GET    /api/auth/devices            — { devices: [{ id, agent, at, via, current }], twoStep }
 * DELETE /api/auth/devices            — sign out every OTHER device
 * DELETE /api/auth/devices?id=<id>    — sign out that one
 *
 * Sessions are tokens in the browser; what makes them revocable is their id
 * on the person's row (`signedInDevices`, written at sign-in by `auth.ts`).
 * A session whose id is gone is refused at its next request — within thirty
 * seconds (`stillHeld` in `auth.ts`). Signing out the others also moves the
 * session version on, which withdraws sessions from before ids and every
 * trusted browser; this browser's trust, if it had it, is given back.
 *
 * Forge runtime — do not remove.
 */
import { auth } from "@/auth";
import * as guard from "@/lib/sign-in-guard";

export const runtime = "nodejs";

const said = (status: number, code: string, message: string) => Response.json({ error: { code, message } }, { status });

async function me(): Promise<{ person: guard.Person; sid: string | null } | null> {
  const user = (await auth())?.user as { id?: string; sid?: string | null } | undefined;
  if (!user?.id) return null;
  const person = await guard.readPerson(String(user.id));
  return person ? { person, sid: typeof user.sid === "string" ? user.sid : null } : null;
}

export async function GET(): Promise<Response> {
  const who = await me();
  if (!who) return said(401, "UNAUTHORIZED", "Sign in to see this.");
  const devices = guard.devicesOf(who.person).map((d) => ({ ...d, current: d.id === who.sid }));
  return Response.json({ devices, twoStep: who.person.twoStep === true });
}

export async function DELETE(request: Request): Promise<Response> {
  const who = await me();
  if (!who) return said(401, "UNAUTHORIZED", "Sign in to do this.");
  const one = new URL(request.url).searchParams.get("id");
  if (one) {
    if (one === who.sid) return said(400, "VALIDATION_ERROR", "Sign out of this device with Sign out.");
    await guard.dropDevice(who.person.id, one);
    return Response.json({ ok: true, signedOut: 1 });
  }
  if (!who.sid) return said(409, "OLD_SESSION", "Sign out and in again first, so this device can stay signed in.");
  const before = guard.devicesOf(who.person).length;
  const wasTrusted = guard.trusted(who.person, request.headers.get("cookie") ?? "");
  const version = await guard.keepOnly(who.person, who.sid);
  if (wasTrusted) await guard.trustThisBrowser({ ...who.person, sessionVersion: version });
  return Response.json({ ok: true, signedOut: Math.max(0, before - 1) });
}
