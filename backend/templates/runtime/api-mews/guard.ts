/**
 * Who may manage the application's Mews properties: its administrator (the
 * role the built-in admin account holds) and the platform's own roles.
 * 401 signed out → 404 the application declares no Mews integration → 403
 * anyone else. Forge runtime — do not remove.
 */
import { auth } from "@/auth";
import { ADMIN_ROLE } from "@/lib/account";
import { isPlatformRole } from "@/lib/tenancy";
import { MewsError, mewsOn } from "@/lib/mews";

export type Guarded = { ok: true; user: { id: string; role: string } } | { ok: false; response: Response };

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
}

export async function mewsAdmin(): Promise<Guarded> {
  const user = (await auth())?.user as { id?: unknown; role?: unknown } | undefined;
  if (!user?.id) return { ok: false, response: json({ error: "Sign in first." }, 401) };
  if (!mewsOn()) return { ok: false, response: json({ error: "This application has no Mews integration." }, 404) };
  const role = String(user.role ?? "");
  if (role !== (ADMIN_ROLE ?? "admin") && !isPlatformRole(role)) {
    return { ok: false, response: json({ error: "Only the application's administrator manages its Mews properties." }, 403) };
  }
  return { ok: true, user: { id: String(user.id), role } };
}

/** Anyone signed in to an application that declares Mews: who searches it. */
export async function mewsUser(): Promise<Guarded> {
  const user = (await auth())?.user as { id?: unknown; role?: unknown } | undefined;
  if (!user?.id) return { ok: false, response: json({ error: "Sign in first." }, 401) };
  if (!mewsOn()) return { ok: false, response: json({ error: "This application has no Mews integration." }, 404) };
  return { ok: true, user: { id: String(user.id), role: String(user.role ?? "") } };
}

/** A refusal the administrator can act on, or a failure said plainly — never a token. */
export function failed(err: unknown): Response {
  if (err instanceof MewsError) return json({ error: err.message }, err.status);
  console.error("[mews]", err);
  return json({ error: "Mews could not be asked just now. Try again." }, 500);
}

export async function readJson(req: Request): Promise<Record<string, unknown>> {
  try {
    const body = await req.json();
    return body && typeof body === "object" && !Array.isArray(body) ? body : {};
  } catch {
    return {};
  }
}
