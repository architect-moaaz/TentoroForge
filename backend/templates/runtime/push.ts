/**
 * Push notifications to a person's subscribed devices (Web Push, VAPID).
 *
 * The application's own VAPID keys (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`,
 * `VAPID_SUBJECT`) sign every message; they are generated for the project
 * when it is first assembled and kept across rebuilds, because a rotated
 * key orphans every subscription a device has made. A device that answers
 * 404 or 410 has unsubscribed, and its row is removed. With no keys set,
 * nothing is sent and the caller is told so.
 *
 * Forge runtime — do not remove.
 */
import { db } from "@/db";
import { forgePushSubscriptions } from "@/db/schema/_forge_push_subscriptions";
import { eq, inArray } from "drizzle-orm";

export interface PushPayload { title: string; body?: string; link?: string | null; tag?: string }

export function pushConfigured(env: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(env.VAPID_PUBLIC_KEY && env.VAPID_PRIVATE_KEY);
}

export function publicKey(env: NodeJS.ProcessEnv = process.env): string {
  return String(env.VAPID_PUBLIC_KEY ?? "");
}

async function _webPush(): Promise<any | null> {
  try {
    // By name at runtime: the package is added to the app's dependencies by
    // the platform; an app built before it existed still compiles.
    const name = "web-push";
    const mod: any = await import(/* webpackIgnore: true */ name);
    return mod.default ?? mod;
  } catch {
    return null;
  }
}

/** The user ids that hold `role`, for a notification sent by role. */
async function _usersOfRole(role: string): Promise<string[]> {
  try {
    const { sql } = await import("drizzle-orm");
    const res: any = await (db as any).execute(sql`SELECT id FROM users WHERE role = ${role} OR account_type = ${role}`);
    const rows = Array.isArray(res) ? res : (res?.rows ?? []);
    return rows.map((r: any) => String(r.id));
  } catch {
    try {
      const { sql } = await import("drizzle-orm");
      const res: any = await (db as any).execute(sql`SELECT id FROM users WHERE role = ${role}`);
      const rows = Array.isArray(res) ? res : (res?.rows ?? []);
      return rows.map((r: any) => String(r.id));
    } catch {
      return [];
    }
  }
}

/**
 * Send `payload` to every device of `to` (user ids, or a role). Returns how
 * many devices were reached, how many were pruned, and why nothing went
 * when nothing did.
 */
export async function sendPush(to: { userIds?: string[]; role?: string }, payload: PushPayload,
                               env: NodeJS.ProcessEnv = process.env): Promise<{ sent: number; pruned: number; notice?: string }> {
  if (!pushConfigured(env)) return { sent: 0, pruned: 0, notice: "push is not configured here: VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are unset" };
  const wp = await _webPush();
  if (!wp) return { sent: 0, pruned: 0, notice: "the web-push package is not installed" };
  wp.setVapidDetails(String(env.VAPID_SUBJECT || "mailto:notifications@example.com"), String(env.VAPID_PUBLIC_KEY), String(env.VAPID_PRIVATE_KEY));
  const ids = [...(to.userIds ?? []), ...(to.role ? await _usersOfRole(to.role) : [])].filter(Boolean);
  if (ids.length === 0) return { sent: 0, pruned: 0, notice: "nobody to send to" };
  const rows = await db.select().from(forgePushSubscriptions).where(inArray(forgePushSubscriptions.userId, ids));
  if (rows.length === 0) return { sent: 0, pruned: 0, notice: "no device is subscribed" };
  let sent = 0;
  let pruned = 0;
  const body = JSON.stringify({ title: payload.title, body: payload.body ?? "", link: payload.link ?? null, tag: payload.tag });
  for (const row of rows) {
    try {
      await wp.sendNotification({ endpoint: row.endpoint, keys: { p256dh: row.p256dh, auth: row.auth } }, body, { TTL: 60 * 60 });
      sent += 1;
    } catch (err: any) {
      const status = Number(err?.statusCode ?? err?.status ?? 0);
      if (status === 404 || status === 410) {
        pruned += 1;
        try { await db.delete(forgePushSubscriptions).where(eq(forgePushSubscriptions.endpoint, row.endpoint)); } catch { /* next time */ }
      } else {
        console.warn("[push] a device could not be reached:", status || err);
      }
    }
  }
  return { sent, pruned };
}

