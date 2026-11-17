/**
 * "When this happens at this zone, do this."
 *
 *   rule = { onEvent: "geofence.entered", geofenceId?: zone, condition?: "<FEEL-lite>", action, confirm?, sensitive? }
 *
 * Actions are small on purpose: `emit_event` (put a named event on the bus — every workflow already starts from events, so
 * anything bigger is a workflow) and `notify` (a push to people). Both are keyed so a crossing repeated by a retry acts once.
 *
 * THE RULE THAT MATTERS: a crossing is where a phone SAYS it is. It can be wrong (a bad fix), early (the zone is big) or
 * false (a spoofed location). So an action that moves money, finishes a job or marks someone present is SENSITIVE, and a
 * sensitive action does not run on a crossing alone. The rule must name something that is not GPS —
 * `confirm: { event: "order.code_verified" }`, a customer's code, a manager's tap, a scan — and that event must already have
 * been recorded for the same entity. Until then the action is HELD (and says so), never run. A sensitive rule with no
 * `confirm` is held for ever, so a mistake in a rule fails safe.
 *
 * No database and no bus here: everything is handed in (`RuleDeps`), so the rules are tested without either.
 * Forge runtime — do not remove.
 */
import { evaluateExpression } from "../feel-lite";
import type { FenceRules, GeofenceEvent } from "./engine";

export type RuleAction =
  | { kind: "emit_event"; event: string; payload?: Record<string, unknown> }
  | { kind: "notify"; title: string; body?: string; link?: string; role?: string; userIds?: string[] };

export type Rule = {
  id: string;
  /** null = every zone */
  geofenceId: string | null;
  onEvent: string;
  condition?: string | null;
  action: RuleAction;
  sensitive?: boolean;
  /** Evidence that is not GPS: an event of this type must already exist for the same entity (within `withinSec`, if given). */
  confirm?: { event: string; withinSec?: number } | null;
  active?: boolean;
};

export type Outcome = "done" | "held" | "skipped" | "duplicate" | "failed";
export type RuleResult = { ruleId: string; outcome: Outcome; reason?: string };

export interface RuleDeps {
  rules: Rule[];
  /** True the first time `key` is claimed, false after: what makes a repeated crossing act once. */
  claim(key: string): Promise<boolean>;
  emit(type: string, opts: { entity: string; entityId: string; payload: Record<string, unknown>; dedupeKey: string }): Promise<void>;
  notify(to: { role?: string; userIds?: string[] }, message: { title: string; body?: string; link?: string; tag?: string }): Promise<void>;
  /** Was an event of this type recorded for this entity, not older than `withinSec`? */
  hasEvidence(entityType: string, entityId: string, eventType: string, sinceMs: number | null): Promise<boolean>;
  now?: () => number;
}

/** Words that mark an action as moving money, finishing a job or marking someone present. */
export const SENSITIVE = /(paid|payment|charge|refund|payout|settle|deliver|complet|finish|fulfil|close|attend|present|clock|check(?:ed)?[-_. ]?(?:in|out)|sign[-_. ]?off|approve)/i;

export function isSensitive(rule: Rule): boolean {
  if (rule.sensitive) return true;
  return rule.action.kind === "emit_event" && SENSITIVE.test(rule.action.event);
}

/** `{{event.entityId}}`, `{{metadata.dwellMs}}`, `{{zone}}` — filled from the crossing. Unknown names become empty. */
export function fill(text: string, e: GeofenceEvent): string {
  const scope: Record<string, unknown> = { event: e, metadata: e.metadata, zone: e.geofenceId, type: e.type, entityType: e.entityType, entityId: e.entityId };
  return text.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_, path: string) => {
    let v: unknown = scope;
    for (const k of path.split(".")) v = v && typeof v === "object" ? (v as Record<string, unknown>)[k] : undefined;
    return v == null ? "" : String(v);
  });
}

function fillValue(v: unknown, e: GeofenceEvent): unknown {
  if (typeof v === "string") return fill(v, e);
  if (Array.isArray(v)) return v.map((x) => fillValue(x, e));
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, fillValue(x, e)]));
  return v;
}

/** Rules that apply to this crossing, in the order they were given. A broken condition makes the rule not apply. */
export function matching(e: GeofenceEvent, rules: Rule[]): Rule[] {
  return rules.filter((r) => {
    if (r.active === false) return false;
    if (r.onEvent !== e.type) return false;
    if (r.geofenceId && r.geofenceId !== e.geofenceId) return false;
    if (!r.condition) return true;
    try {
      return !!evaluateExpression(r.condition, { event: e, metadata: e.metadata, entityType: e.entityType, entityId: e.entityId, zone: e.geofenceId });
    } catch {
      return false;
    }
  });
}

/** Run the rules a crossing triggers. Never throws: each rule's outcome is returned, a failure is one rule's failure. */
export async function runRules(e: GeofenceEvent, deps: RuleDeps): Promise<RuleResult[]> {
  const now = (deps.now ?? Date.now)();
  const out: RuleResult[] = [];
  for (const rule of matching(e, deps.rules)) {
    try {
      if (isSensitive(rule)) {
        if (!rule.confirm?.event) {
          out.push({ ruleId: rule.id, outcome: "held", reason: "This moves money, finishes a job or marks someone present, so it needs a confirmation that is not GPS, and the rule names none." });
          continue;
        }
        const since = rule.confirm.withinSec ? now - rule.confirm.withinSec * 1000 : null;
        if (!(await deps.hasEvidence(e.entityType, e.entityId, rule.confirm.event, since))) {
          out.push({ ruleId: rule.id, outcome: "held", reason: `Waiting for "${rule.confirm.event}": being in the zone is not enough.` });
          continue;
        }
      }
      if (!(await deps.claim(`geofence-rule:${rule.id}:${e.id}`))) {
        out.push({ ruleId: rule.id, outcome: "duplicate" });
        continue;
      }
      const a = rule.action;
      if (a.kind === "emit_event") {
        const payload = { ...(fillValue(a.payload ?? {}, e) as Record<string, unknown>), geofenceEvent: e.id, geofenceId: e.geofenceId, entityType: e.entityType, entityId: e.entityId };
        await deps.emit(fill(a.event, e), { entity: e.entityType, entityId: e.entityId, payload, dedupeKey: `geofence-action:${rule.id}:${e.id}` });
      } else if (a.kind === "notify") {
        await deps.notify({ role: a.role, userIds: a.userIds?.map((u) => fill(u, e)).filter(Boolean) }, { title: fill(a.title, e), body: a.body ? fill(a.body, e) : undefined, link: a.link ? fill(a.link, e) : undefined, tag: `geofence-${e.id}` });
      } else {
        out.push({ ruleId: rule.id, outcome: "skipped", reason: `Unknown action "${(a as { kind?: string }).kind}".` });
        continue;
      }
      out.push({ ruleId: rule.id, outcome: "done" });
    } catch (err) {
      out.push({ ruleId: rule.id, outcome: "failed", reason: String(err) });
    }
  }
  return out;
}

/** Why a rule as written cannot work, or null. Used when a rule is saved. */
export function invalidRule(r: Partial<Rule>): string | null {
  if (!r.onEvent || !/^geofence\.(entered|exited|dwell|approaching)$/.test(r.onEvent)) return "A rule starts from entered, exited, dwell or approaching.";
  const a = r.action as RuleAction | undefined;
  if (!a || typeof a !== "object") return "A rule needs an action.";
  if (a.kind === "emit_event" && !(typeof a.event === "string" && a.event.trim())) return "emit_event needs the event's name.";
  if (a.kind === "notify" && !(typeof a.title === "string" && a.title.trim())) return "notify needs a title.";
  if (a.kind === "notify" && !a.role && !(a.userIds && a.userIds.length)) return "notify needs a role or people to tell.";
  if (a.kind !== "emit_event" && a.kind !== "notify") return "An action is emit_event or notify.";
  if (r.condition) {
    try { evaluateExpression(r.condition, { event: {}, metadata: {}, entityType: "", entityId: "", zone: "" }); } catch (err) { return `The condition does not work: ${String(err).slice(0, 120)}`; }
  }
  return null;
}

// ---------------------------------------------------------------------------------------------------------------------
// Releasing what was held
// ---------------------------------------------------------------------------------------------------------------------

export type Held = { rule: Rule; event: GeofenceEvent; heldAt: number };

export interface ReleaseDeps extends Omit<RuleDeps, "rules"> {
  /** Held actions for this entity whose rule waits for `confirmEvent`. */
  heldFor(entityType: string, entityId: string, confirmEvent: string): Promise<Held[]>;
  /** A hold older than this (seconds) is let go, not run: the crossing is too old to still mean anything. Default 6 hours. */
  maxAgeSec?: number;
}

/**
 * The confirmation has arrived (`confirmEvent` was recorded for this entity): run what was waiting for it.
 * Each held crossing is run through its own rule again, so the guard is checked again, the claim is taken, and a crossing
 * that already acted does nothing twice.
 */
export async function releaseHeld(confirmEvent: string, entityType: string, entityId: string, deps: ReleaseDeps): Promise<RuleResult[]> {
  const now = (deps.now ?? Date.now)();
  const maxAge = (deps.maxAgeSec ?? 6 * 3600) * 1000;
  const seen = new Set<string>();
  const out: RuleResult[] = [];
  for (const h of await deps.heldFor(entityType, entityId, confirmEvent)) {
    const key = `${h.rule.id}:${h.event.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    if (now - h.heldAt > maxAge) { out.push({ ruleId: h.rule.id, outcome: "skipped", reason: "Held too long ago to still mean anything." }); continue; }
    out.push(...(await runRules(h.event, { ...deps, rules: [h.rule] })));
  }
  return out;
}

/**
 * May this role change zones? `allowed` is the list from FORGE_GEOFENCE_ROLES (default "admin"). Roles are compared
 * without regard to case: apps name them "Admin", "Restaurant Manager", and a check that needed the exact spelling
 * locked the admin out of the screens built for them.
 */
export function isManagerRole(role: unknown, allowed: string[]): boolean {
  const r = String(role ?? "").trim().toLowerCase();
  return r !== "" && allowed.some((a) => a.trim().toLowerCase() === r);
}

/** Rule fields a person may set, each held to a sane range; anything else is dropped. */
export function cleanFenceRules(input: unknown): { rules: FenceRules; problem?: string } {
  const r = (input && typeof input === "object" ? input : {}) as Record<string, unknown>;
  const out: FenceRules = {};
  const num = (k: string, min: number, max: number): string | undefined => {
    if (r[k] == null || r[k] === "") return;
    const v = Number(r[k]);
    if (!Number.isFinite(v) || v < min || v > max) return `${k} must be a number from ${min} to ${max}.`;
    (out as Record<string, unknown>)[k] = v;
  };
  for (const [k, lo, hi] of [["dwellSec", 1, 86_400], ["approachM", 1, 50_000], ["hysteresisM", 0, 1_000], ["minFixes", 1, 10], ["maxAccuracyM", 5, 1_000], ["staleMs", 1_000, 3_600_000], ["maxGapMs", 10_000, 86_400_000]] as const) {
    const bad = num(k, lo, hi);
    if (bad) return { rules: {}, problem: bad };
  }
  if (typeof r.enter === "boolean") out.enter = r.enter;
  if (typeof r.exit === "boolean") out.exit = r.exit;
  return { rules: out };
}
