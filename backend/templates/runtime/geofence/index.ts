/**
 * The geofence service as an app uses it: Postgres for storage, the durable event bus for announcements.
 *
 *   await checkPosition({ entityType: "Order", entityId }, { lat, lng, at, accuracy })
 *
 * NEVER throws and never slows the caller more than one round of queries: an app without the geofence tables, a database
 * blip, a bad zone — each is logged once and the position goes on to its map as before.
 * Forge runtime — do not remove.
 */
import { emitEvent, emitEventAndProcess } from "@/lib/events/bus";
import { makeGeofenceService, type Subject } from "./service";
import { postgresGeofenceStore, loadRules, hasEvidence, heldFor, purgeOld } from "./store";
import { purgeDue } from "./privacy";
import { runRules, releaseHeld, type Rule, type RuleDeps, type ReleaseDeps } from "./rules";
import { publishCrossing } from "./hub";
import type { GeofenceEvent } from "./engine";

let rulesCache: { at: number; rules: Rule[] } | null = null;
async function rules(): Promise<Rule[]> {
  if (rulesCache && Date.now() - rulesCache.at < 30_000) return rulesCache.rules;
  rulesCache = { at: Date.now(), rules: await loadRules().catch(() => []) };
  return rulesCache.rules;
}

/** A rule was added or changed: look again at once. */
export function rulesChanged(): void { rulesCache = null; }

/**
 * Tell people a zone rule fired: an IN-APP notification first (the bell every app has: a row naming the person, or naming
 * nobody and their role), then a web push. Push alone reached only a browser that had subscribed to it, so an admin who never
 * had was told nothing and nothing was recorded (found building a fleet app end to end, 2026-11-18). The push is best effort;
 * the rule fails only when NEITHER reached anyone.
 */
async function notifyPeople(to: { role?: string; userIds?: string[] }, m: { title: string; body?: string; link?: string; tag?: string }): Promise<void> {
  let inApp = false;
  try {
    const { db } = await import("@/db");
    const { forgeNotifications } = await import("@/db/schema/_forge_notifications");
    const base = { title: m.title, message: m.body ?? "", type: "info", link: m.link ?? null };
    const rows = to.userIds?.length
      ? to.userIds.map((u) => ({ ...base, userId: String(u), role: to.role ?? null }))
      : to.role ? [{ ...base, userId: null, role: to.role }] : [];
    if (rows.length) { await db.insert(forgeNotifications).values(rows); inApp = true; }
  } catch { /* an app with no notifications table still gets the push below */ }
  try {
    const { sendPush } = await import("@/lib/push");
    await sendPush(to, m);
  } catch (err) {
    if (!inApp) throw err;
  }
}

const ruleDeps = (): Omit<RuleDeps, "rules"> => ({
  // The bus's own dedupe key says whether this is the first time: {id} is new, {duplicate} is not.
  claim: async (key) => { const r = await emitEvent("geofence.rule_claimed", { dedupeKey: key }); return !!r && "id" in r; },
  emit: async (type, o) => { await emitEventAndProcess(type, o); },
  notify: notifyPeople,
  hasEvidence,
});

/**
 * The confirmation a held action was waiting for has been recorded: run what waited for it. Called by the event bus for
 * every event it processes; it costs nothing unless some rule names that event as its confirmation.
 */
export async function confirmationArrived(evt: { type: string; entity: string | null; entity_id: string | null }): Promise<void> {
  if (!evt.entity || !evt.entity_id || evt.type.startsWith("geofence.")) return;
  if (!(await rules()).some((r) => r.confirm?.event === evt.type)) return;
  const deps: ReleaseDeps = { ...ruleDeps(), heldFor };
  await releaseHeld(evt.type, evt.entity, evt.entity_id, deps);
}

/** Work through the rules a crossing triggers. A held or failed rule is put on the bus so it can be seen, never lost. */
async function actOn(e: GeofenceEvent): Promise<void> {
  const list = await rules();
  if (!list.length) return;
  const deps: RuleDeps = { rules: list, ...ruleDeps() };
  for (const r of await runRules(e, deps)) {
    if (r.outcome === "held" || r.outcome === "failed") {
      await emitEvent("geofence.action_" + r.outcome, { entity: e.entityType, entityId: e.entityId, payload: { ruleId: r.ruleId, reason: r.reason, geofenceEvent: e.id }, dedupeKey: `geofence-${r.outcome}:${r.ruleId}:${e.id}` });
    }
  }
}

const g = globalThis as unknown as { __forgeGeofence?: ReturnType<typeof makeGeofenceService>; __forgeGeofenceWarned?: boolean };

export function geofenceService() {
  return (g.__forgeGeofence ??= makeGeofenceService({
    store: postgresGeofenceStore,
    announce: async (e) => {
      publishCrossing(e);
      await emitEventAndProcess(e.type, { entity: e.entityType, entityId: e.entityId, payload: { ...e }, dedupeKey: `geofence:${e.id}` });
      await actOn(e);
    },
  }));
}

/** A zone was added, moved or switched off: look again at once. */
export function zonesChanged(): void {
  g.__forgeGeofence?.invalidate();
}

/** Old crossings are deleted (see privacy.ts), at most once an hour, in the background, and never a reason for a position to fail. */
let lastPurge = 0;
function tidy(): void {
  const now = Date.now();
  if (!purgeDue(lastPurge, now)) return;
  lastPurge = now;
  void purgeOld(now).catch(() => { /* tables missing or a blip: the next hour tries again */ });
}

export async function checkPosition(
  who: Subject,
  fix: { lat: number; lng: number; at: number; accuracy?: number },
  opts: { replay?: boolean } = {},
): Promise<void> {
  try {
    await geofenceService().ingest(who, fix, opts);
    tidy();
  } catch (err) {
    if (!g.__forgeGeofenceWarned) {
      g.__forgeGeofenceWarned = true;
      console.warn("[geofence] position not checked (this is logged once):", err);
    }
  }
}
