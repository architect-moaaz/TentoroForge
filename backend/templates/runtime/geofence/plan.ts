/**
 * What the brief said about zones, put into the app: the zones that came with coordinates, and the rules that belong to them.
 *
 *   plan = { zones: [{ name, radiusM, lat, lng, needsDrawing }], rules: [{ zone, onEvent, action, note }] }
 *
 * Written by Forge from the brief (`services/blueprint/geofence_plan.py`) and read from `contracts/geofence-plan.json`.
 * Safe to run on every start: a zone is found by its name and a rule by its zone, event and action, so nothing is added twice,
 * and a zone or rule a person changed or removed later is not put back (a zone that is there is left as it is).
 *
 *   * A zone with no coordinates is NOT created: nothing guesses where a restaurant is. The owner draws it.
 *   * A rule is bound to its zone by name and is created only when that zone exists. It is never left loose, because a rule for
 *     "the customer's door" firing at every zone would be wrong.
 *   * Every rule is checked as the rules screen checks it (`invalidRule`); a bad one is reported, not stored.
 *
 * No database here: the caller hands in how to look up and add things, so this is tested without one.
 * Forge runtime — do not remove.
 */
import { cleanFenceRules, invalidRule, isSensitive, type Rule } from "./rules";

export type PlanZone = { name: string; radiusM: number; lat?: number | null; lng?: number | null; needsDrawing?: boolean; purpose?: string; rules?: Record<string, number> };
export type PlanRule = { zone: string | null; onEvent: string; action: Record<string, unknown>; note?: string };
export type GeofencePlan = { zones?: PlanZone[]; rules?: PlanRule[] };

export interface PlanIO {
  zoneId(name: string): Promise<string | null>;
  addZone(z: { name: string; lat: number; lng: number; radiusM: number; rules: Record<string, unknown> }): Promise<string>;
  hasRule(zoneId: string | null, onEvent: string, action: Record<string, unknown>): Promise<boolean>;
  addRule(r: { geofenceId: string | null; onEvent: string; action: Record<string, unknown>; sensitive: boolean }): Promise<void>;
}

export type PlanResult = {
  zonesAdded: string[];
  zonesKept: string[];
  /** Zones the owner still has to draw. */
  zonesToDraw: string[];
  rulesAdded: number;
  rulesKept: number;
  /** Rules that were not stored, and why. */
  rulesRefused: { zone: string | null; onEvent: string; reason: string }[];
  /** Rules whose zone is not there yet. */
  rulesWaiting: { zone: string | null; onEvent: string }[];
};

const finite = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

export async function applyPlan(plan: GeofencePlan | null | undefined, io: PlanIO): Promise<PlanResult> {
  const out: PlanResult = { zonesAdded: [], zonesKept: [], zonesToDraw: [], rulesAdded: 0, rulesKept: 0, rulesRefused: [], rulesWaiting: [] };
  if (!plan || typeof plan !== "object") return out;
  const ids = new Map<string, string>();
  for (const z of plan.zones ?? []) {
    if (!z || typeof z.name !== "string" || !z.name.trim()) continue;
    const name = z.name.trim();
    const have = await io.zoneId(name);
    if (have) { ids.set(name.toLowerCase(), have); out.zonesKept.push(name); continue; }
    const ok = !z.needsDrawing && finite(z.lat) && finite(z.lng) && finite(z.radiusM)
      && Math.abs(z.lat) <= 90 && Math.abs(z.lng) <= 180 && z.radiusM >= 5 && z.radiusM <= 50_000;
    if (!ok) { out.zonesToDraw.push(name); continue; }
    // The zone's settings are checked as the zones screen checks them; a bad set is dropped, the zone is still made.
    const cleaned = cleanFenceRules(z.rules ?? {});
    ids.set(name.toLowerCase(), await io.addZone({ name, lat: z.lat as number, lng: z.lng as number, radiusM: z.radiusM, rules: cleaned.problem ? {} : cleaned.rules }));
    out.zonesAdded.push(name);
  }
  for (const r of plan.rules ?? []) {
    if (!r || typeof r.onEvent !== "string") continue;
    let geofenceId: string | null = null;
    if (r.zone) {
      geofenceId = ids.get(r.zone.toLowerCase()) ?? (await io.zoneId(r.zone));
      if (!geofenceId) { out.rulesWaiting.push({ zone: r.zone, onEvent: r.onEvent }); continue; }
    }
    const rule = { onEvent: r.onEvent, action: r.action } as Partial<Rule>;
    const bad = invalidRule(rule);
    if (bad) { out.rulesRefused.push({ zone: r.zone, onEvent: r.onEvent, reason: bad }); continue; }
    if (await io.hasRule(geofenceId, r.onEvent, r.action)) { out.rulesKept++; continue; }
    await io.addRule({ geofenceId, onEvent: r.onEvent, action: r.action, sensitive: isSensitive(rule as Rule) });
    out.rulesAdded++;
  }
  return out;
}
