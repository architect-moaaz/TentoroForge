/**
 * Who may do what with zones.
 *
 *   read zones   any signed-in person (a zone is a place on the map, like a restaurant's pin)
 *   change them  the roles named in FORGE_GEOFENCE_ROLES (default "admin"), as in `a,b`
 *
 * Crossings are not read through here: they follow the app's own read rules for the record they are about
 * (see api/geofence/events and the stream).
 * Forge runtime — do not remove.
 */
import { auth } from "@/auth";
import { isManagerRole } from "./rules";

export type Who = { ok: true; userId: string; role: string; manager: boolean } | { ok: false; status: 401; error: string };

export function managerRoles(env: NodeJS.ProcessEnv = process.env): string[] {
  return String(env.FORGE_GEOFENCE_ROLES ?? "admin").split(",").map((r) => r.trim()).filter(Boolean);
}

export async function who(): Promise<Who> {
  const user = (await auth().catch(() => null))?.user as { id?: unknown; email?: unknown; role?: unknown } | undefined;
  const userId = user?.id ?? user?.email;
  if (!userId) return { ok: false, status: 401, error: "Sign in to see the zones." };
  const role = String(user?.role ?? "");
  return { ok: true, userId: String(userId), role, manager: isManagerRole(role, managerRoles()) };
}

export const refuse = (status: number, error: string) => Response.json({ ok: false, error }, { status });
