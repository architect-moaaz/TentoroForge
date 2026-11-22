/**
 * Push notifications to a person's devices: their BROWSERS (Web Push, VAPID) and their PHONES (the native app, through Expo).
 *
 * The application's own VAPID keys (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`,
 * `VAPID_SUBJECT`) sign every message; they are generated for the project
 * when it is first assembled and kept across rebuilds, because a rotated
 * key orphans every subscription a device has made. A device that answers
 * 404 or 410 has unsubscribed, and its row is removed. With no keys set,
 * no browser is reached and the caller is told so. A phone needs no key of the app's own: the native app registers its Expo
 * token (`/api/push/device`, table `forge_device_tokens`) and an alert goes to every phone a person has.
 *
 * Forge runtime — do not remove.
 */
import { db } from "@/db";
import { forgePushSubscriptions } from "@/db/schema/_forge_push_subscriptions";
import { forgeDeviceTokens } from "@/db/schema/_forge_device_tokens";
import { eq, inArray } from "drizzle-orm";
import { sendExpo, validExpoToken, type PushPayload } from "@/lib/expo-push";

export type { PushPayload };

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
 * Send `payload` to every device of `to` (user ids, or a role): each browser and each phone. Returns how many devices were
 * reached (`web` and `phones` say which), how many were pruned, and why nothing went when nothing did.
 */
export async function sendPush(to: { userIds?: string[]; role?: string }, payload: PushPayload,
                               env: NodeJS.ProcessEnv = process.env): Promise<{ sent: number; pruned: number; web: number; phones: number; notice?: string }> {
  const ids = [...new Set([...(to.userIds ?? []), ...(to.role ? await _usersOfRole(to.role) : [])].filter(Boolean))];
  if (ids.length === 0) return { sent: 0, pruned: 0, web: 0, phones: 0, notice: "nobody to send to" };
  let web = 0;
  let phones = 0;
  let pruned = 0;
  let webNotice: string | undefined;
  let phoneNotice: string | undefined;

  // browsers (Web Push)
  if (!pushConfigured(env)) {
    webNotice = "push is not configured here: VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are unset";
  } else {
    const wp = await _webPush();
    if (!wp) {
      webNotice = "the web-push package is not installed";
    } else {
      wp.setVapidDetails(String(env.VAPID_SUBJECT || "mailto:notifications@example.com"), String(env.VAPID_PUBLIC_KEY), String(env.VAPID_PRIVATE_KEY));
      const rows = await db.select().from(forgePushSubscriptions).where(inArray(forgePushSubscriptions.userId, ids));
      if (rows.length === 0) webNotice = "no device is subscribed";
      const body = JSON.stringify({ title: payload.title, body: payload.body ?? "", link: payload.link ?? null, tag: payload.tag });
      for (const row of rows) {
        try {
          await wp.sendNotification({ endpoint: row.endpoint, keys: { p256dh: row.p256dh, auth: row.auth } }, body, { TTL: payload.ttl && payload.ttl > 0 ? Math.round(payload.ttl) : 60 * 60 });
          web += 1;
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
    }
  }

  // phones (the native app, through Expo)
  try {
    const rows: any[] = await db.select().from(forgeDeviceTokens).where(inArray(forgeDeviceTokens.userId, ids));
    const tokens = rows.map((r) => r?.token).filter(validExpoToken);
    if (tokens.length === 0) {
      phoneNotice = "no phone is registered";
    } else {
      const out = await sendExpo(tokens, payload, { env });
      phones = out.sent;
      if (out.notice) phoneNotice = out.notice;
      if (out.dead.length) {
        pruned += out.dead.length;
        try { await db.delete(forgeDeviceTokens).where(inArray(forgeDeviceTokens.token, out.dead)); } catch { /* next time */ }
      }
    }
  } catch (err) {
    phoneNotice = `phones could not be reached: ${err instanceof Error ? err.message : String(err)}`;
  }

  const sent = web + phones;
  // a reason only when nothing went: the browser's is first (it names the keys to set), then the phone's
  const notice = sent === 0 ? (webNotice && !/no device is subscribed/.test(webNotice) ? webNotice : phoneNotice ?? webNotice) : undefined;
  return { sent, pruned, web, phones, ...(notice ? { notice } : {}) };
}
