/**
 * Reads the job a tracking request is about, as the person asking.
 *
 * The data engine's own `findById` is used, so the app's ownership and row
 * rules decide who may follow — "if you may open this order, you may follow its
 * driver". A job this person may not see is "not found", the same as one that
 * does not exist: the answer is not an oracle for which trips are running.
 *
 * Forge runtime — do not remove.
 */
import { auth } from "@/auth";
import * as engine from "@/lib/data-engine";
import { actorCtx } from "@/lib/data-engine-bridge";
import { ensureDataEngineInitialized } from "@/lib/data-init";

export type Job =
  | { ok: true; userId: string; job: Record<string, unknown> }
  | { ok: false; status: 401 | 404; error: string };

/** The signed-in person, or null. */
export async function whoIs(): Promise<{ userId: string; user: Record<string, unknown> } | null> {
  const session = await auth().catch(() => null);
  const user = session?.user as Record<string, unknown> | undefined;
  const userId = (user?.id ?? user?.email) as string | undefined;
  return user && userId ? { userId: String(userId), user } : null;
}

export async function jobFor(entity: string, id: string): Promise<Job> {
  const me = await whoIs();
  if (!me) return { ok: false, status: 401, error: "Sign in to follow or share a trip." };
  const { user, userId } = me;

  await ensureDataEngineInitialized();
  try {
    const job = (await engine.findById(entity, id, actorCtx(user) as never)) as Record<string, unknown>;
    return { ok: true, userId, job };
  } catch {
    return { ok: false, status: 404, error: "No such trip." };
  }
}

export type Visible =
  | { ok: true; userId: string; rows: Map<string, Record<string, unknown>> }
  | { ok: false; status: 401 | 404; error: string };

/**
 * Every record of this kind the signed-in person may see, by id. The data
 * engine's own read rules decide: an admin sees every driver, a driver sees
 * only themselves, a stranger sees none. The fleet map shows exactly these.
 */
export async function visibleMembers(entity: string): Promise<Visible> {
  const me = await whoIs();
  if (!me) return { ok: false, status: 401, error: "Sign in to see the map." };
  await ensureDataEngineInitialized();
  try {
    const res = await engine.query(entity, { limit: 500 }, actorCtx(me.user) as never);
    const rows = new Map<string, Record<string, unknown>>();
    for (const r of res.data as Record<string, unknown>[]) if (typeof r.id === "string") rows.set(r.id, r);
    return { ok: true, userId: me.userId, rows };
  } catch {
    return { ok: false, status: 404, error: "No such fleet." };
  }
}
