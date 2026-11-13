/**
 * Alerts to a person's PHONE through Expo's push service — the native app's side of push.
 *
 * A phone app tells the server its Expo push token (`ExponentPushToken[...]`, see /api/push/device); this module posts
 * the message to Expo (https://exp.host/--/api/v2/push/send), which hands it to Google's or Apple's service for that
 * phone. No key of the app's own is needed for that (an `EXPO_ACCESS_TOKEN` is used when the app sets one, for Expo's
 * "enhanced security"). A token Expo says is `DeviceNotRegistered` belongs to an app that was uninstalled: it is handed
 * back so the caller forgets it.
 *
 * Pure: the network is passed in (`fetch`), so the whole of it can be tested without one.
 *
 * Forge runtime — do not remove.
 */

export interface PushPayload {
  title: string;
  body?: string;
  link?: string | null;
  tag?: string;
  /** How long Expo may hold the message for a phone that is out of reach, in seconds. A ride offer is stale in a minute or two. */
  ttl?: number;
}

export interface ExpoMessage {
  to: string;
  title: string;
  body: string;
  sound: "default";
  priority: "high";
  channelId: "default";
  ttl: number;
  data: { link: string | null; tag?: string };
}

export const EXPO_SEND_URL = "https://exp.host/--/api/v2/push/send";
/** Expo accepts at most 100 messages in one request. */
export const EXPO_BATCH = 100;

/** True for the address a phone gets from Expo. */
export function validExpoToken(token: unknown): token is string {
  return typeof token === "string" && /^Expo(nent)?PushToken\[[^\]\s]+\]$/.test(token);
}

export function expoMessages(tokens: string[], payload: PushPayload): ExpoMessage[] {
  const link = typeof payload.link === "string" && payload.link.startsWith("/") ? payload.link : null;
  return tokens.filter(validExpoToken).map((to) => ({
    to,
    title: payload.title,
    body: payload.body ?? "",
    sound: "default" as const,
    priority: "high" as const,
    channelId: "default" as const,
    ttl: payload.ttl && payload.ttl > 0 ? Math.round(payload.ttl) : 3600,
    data: { link, ...(payload.tag ? { tag: payload.tag } : {}) },
  }));
}

export interface ExpoDeps {
  fetch?: typeof fetch;
  env?: Record<string, string | undefined>;
}

/**
 * Send `payload` to each token. Returns how many Expo accepted, the tokens to forget, and a `notice` (in words) when a
 * batch could not be delivered to Expo at all. Never throws: an alert that cannot go must not fail the work that asked.
 */
export async function sendExpo(tokens: string[], payload: PushPayload, deps: ExpoDeps = {}): Promise<{ sent: number; dead: string[]; notice?: string }> {
  const messages = expoMessages([...new Set(tokens)], payload);
  if (messages.length === 0) return { sent: 0, dead: [] };
  const doFetch = deps.fetch ?? fetch;
  const access = deps.env?.EXPO_ACCESS_TOKEN ?? (typeof process !== "undefined" ? process.env.EXPO_ACCESS_TOKEN : undefined);
  let sent = 0;
  const dead: string[] = [];
  let notice: string | undefined;
  for (let i = 0; i < messages.length; i += EXPO_BATCH) {
    const batch = messages.slice(i, i + EXPO_BATCH);
    try {
      const res = await doFetch(EXPO_SEND_URL, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json", ...(access ? { Authorization: `Bearer ${access}` } : {}) },
        body: JSON.stringify(batch),
      });
      if (!res.ok) { notice = `Expo's push service answered ${res.status}`; continue; }
      const out: any = await res.json().catch(() => null);
      const tickets: any[] = Array.isArray(out?.data) ? out.data : [];
      batch.forEach((m, k) => {
        const t = tickets[k];
        if (t?.status === "ok") sent += 1;
        else if (t?.details?.error === "DeviceNotRegistered") dead.push(m.to);
        else if (t) notice = `Expo refused an alert: ${String(t.message ?? t.details?.error ?? "unknown")}`;
      });
    } catch (err) {
      notice = `Expo's push service could not be reached: ${err instanceof Error ? err.message : String(err)}`;
    }
  }
  return { sent, dead, ...(notice ? { notice } : {}) };
}
