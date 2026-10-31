/**
 * The audit trail: what happened to a record, by whom, when, before and
 * after — kept so it cannot be changed, and checkable.
 *
 * Written INSIDE the write's transaction (`withAudit`): a write the trail
 * missed is a write that did not happen. Each row carries the hash of the
 * previous row's hash and its own facts, under an advisory lock so the
 * chain has one order; `verifyChain` walks it back. The database refuses
 * UPDATE, DELETE and TRUNCATE on the table (`ensureGuard`, idempotent DDL
 * applied once per process); retention goes through `forge_audit_prune`,
 * which records what it removed as a `prune` row so the chain still
 * verifies past the gap. Nothing here runs when the application declares
 * no trail (`AUDIT.level === "none"`).
 */
import crypto from "node:crypto";
import { sql } from "drizzle-orm";
import { db } from "@/db";
// THE POLICY, READ AT LOAD. It was imported lazily, and the questions asked of
// it (`auditOn`, `regulated`, `reviewers`) are synchronous: a caller that
// asked before anything had loaded it heard "none" — the audit screen said
// "This application keeps no audit trail" on a regulated app, and sign-ins and
// exports went unrecorded (60v142ju, 2026-10-12). Every app carries this file
// (the projection writes it; the injector writes a "none" stub otherwise).
import { AUDIT as PROJECTED_AUDIT } from "./audit-policy";

// THE POLICY, READ ONCE. Projected beside this module; an app built before
// the trail existed has none, which reads as level `none`.
let AUDIT: any = PROJECTED_AUDIT ?? { level: "none", reviewers: [], retentionDays: null, reasonRequired: [] };
let _policyLoaded = false;
async function policy(): Promise<any> {
  if (_policyLoaded) return AUDIT;
  _policyLoaded = true;
  try {
    const mod: any = await import("./audit-policy");
    if (mod?.AUDIT) AUDIT = mod.AUDIT;
  } catch { /* no policy projected: none */ }
  return AUDIT;
}
/** For a caller that cannot await: the policy as last loaded (none until `policy()` ran). */
export function setPolicy(next: any): void { AUDIT = next; _policyLoaded = true; }

export type AuditAction = "create" | "update" | "delete" | "read_sensitive" | "export" | "login" | "login_failed"
  | "invite" | "role_change" | "org_switch" | "prune";

export interface AuditActor {
  id?: string | null;
  role?: string | null;
  orgId?: string | null;
  kind?: "user" | "guest" | "system" | "workflow" | "event";
}

export interface AuditEntry {
  action: AuditAction;
  entity: string;
  entityId?: string | null;
  before?: unknown;
  after?: unknown;
  changed?: string[];
  reason?: string | null;
  actor?: AuditActor;
  via?: string;
  runId?: string | null;
  requestId?: string | null;
  ip?: string | null;
  userAgent?: string | null;
}

/** Bytes of `before`/`after` kept per side; past it the value is cut and said so. */
const SIDE_LIMIT = 64 * 1024;
const LOCK_KEY = "forge_audit";

/** Load the policy, for callers that read `auditOn()` and friends synchronously after. */
export async function ready(): Promise<void> { await policy(); }

export function auditLevel(): "none" | "writes" | "regulated" {
  const level = String((AUDIT as any)?.level ?? "none");
  return level === "writes" || level === "regulated" ? level : "none";
}

export function auditOn(): boolean {
  return auditLevel() !== "none";
}

export function regulated(): boolean {
  return auditLevel() === "regulated";
}

/** The reviewers' roles, by name. */
export function reviewers(): string[] {
  return Array.isArray((AUDIT as any)?.reviewers) ? (AUDIT as any).reviewers.map(String) : [];
}

/** Whether a change to `entity` (table or entity name, any case) needs a reason. */
export function reasonRequired(entity: string): boolean {
  const want = String(entity ?? "").toLowerCase();
  const list: string[] = Array.isArray((AUDIT as any)?.reasonRequired) ? (AUDIT as any).reasonRequired : [];
  return list.some((e) => String(e).toLowerCase() === want);
}

function _rows(res: unknown): any[] {
  return Array.isArray(res) ? res : ((res as { rows?: any[] })?.rows ?? []);
}

function _bounded(value: unknown): unknown {
  if (value === undefined) return null;
  const text = JSON.stringify(value ?? null);
  if (text.length <= SIDE_LIMIT) return value ?? null;
  return { truncated: true, bytes: text.length, head: text.slice(0, SIDE_LIMIT) };
}

/** The columns whose values differ between two snapshots. */
export function changedColumns(before: unknown, after: unknown): string[] {
  const a = (before && typeof before === "object" ? before : {}) as Record<string, unknown>;
  const b = (after && typeof after === "object" ? after : {}) as Record<string, unknown>;
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  const out: string[] = [];
  for (const k of keys) {
    if (k === "updatedAt" || k === "updated_at") continue;
    if (JSON.stringify(a[k] ?? null) !== JSON.stringify(b[k] ?? null)) out.push(k);
  }
  return out.sort();
}

/** A value as it reads back from the database, keys in one order. Postgres
 *  keeps a jsonb object's keys in its own order (shortest first) and a Date
 *  comes back as text, so a hash over the value as written never matched the
 *  value as read: the first entry that recorded a real change broke the
 *  chain, every time (60v142ju, 2026-10-12). */
function canonical(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(canonical);
  if (v && typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(v as object).sort()) out[k] = canonical((v as Record<string, unknown>)[k]);
    return out;
  }
  return v;
}

const plain = (v: unknown): unknown => (v == null ? null : JSON.parse(JSON.stringify(v)));

/** Rows hashed over the canonical form say so; rows from before it do not. */
export const HASH_FORM = "c1:";

/** The hash of one row: the facts, in one order, chained to the previous. */
export function rowHash(facts: { at: string; actorId: string | null; action: string; entity: string; entityId: string | null;
  before: unknown; after: unknown; prevHash: string | null }): string {
  const text = JSON.stringify([facts.at, facts.actorId, facts.action, facts.entity, facts.entityId,
    canonical(plain(facts.before)), canonical(plain(facts.after)), facts.prevHash]);
  return HASH_FORM + crypto.createHash("sha256").update(text).digest("hex");
}

/** How rows were hashed before the canonical form: the value in the order it
 *  was handed in, which a jsonb read-back cannot reproduce. */
function legacyHash(facts: { at: string; actorId: string | null; action: string; entity: string; entityId: string | null;
  before: unknown; after: unknown; prevHash: string | null }): string {
  const text = JSON.stringify([facts.at, facts.actorId, facts.action, facts.entity, facts.entityId,
    facts.before ?? null, facts.after ?? null, facts.prevHash]);
  return crypto.createHash("sha256").update(text).digest("hex");
}

let _guarded = false;
let _guarding: Promise<void> | null = null;

/** The table refuses change and erasure; retention has one door. Idempotent.
 *  ONCE, HOWEVER MANY ASK AT ONCE: two first requests each dropped and created
 *  the trigger, and one answered "already exists" or a deadlock (DITANS trial
 *  copy, 2026-10-31). The second waits for the first; `CREATE OR REPLACE` keeps
 *  two servers on one database from colliding too. */
export async function ensureGuard(executor: any = db): Promise<void> {
  if (_guarded) return;
  if (!_guarding) _guarding = _ensureGuard(executor).finally(() => { _guarding = null; });
  return _guarding;
}

async function _ensureGuard(executor: any): Promise<void> {
  try {
    await executor.execute(sql`
      CREATE OR REPLACE FUNCTION forge_audit_is_append_only() RETURNS trigger AS $fn$
      BEGIN
        RAISE EXCEPTION 'forge_audit is append-only';
      END
      $fn$ LANGUAGE plpgsql;
    `);
    await executor.execute(sql`
      CREATE OR REPLACE TRIGGER forge_audit_no_change BEFORE UPDATE OR DELETE ON forge_audit
      FOR EACH ROW EXECUTE FUNCTION forge_audit_is_append_only()
    `);
    await executor.execute(sql`
      CREATE OR REPLACE TRIGGER forge_audit_no_truncate BEFORE TRUNCATE ON forge_audit
      FOR EACH STATEMENT EXECUTE FUNCTION forge_audit_is_append_only()
    `);
    await executor.execute(sql`
      CREATE OR REPLACE FUNCTION forge_audit_prune(before_at timestamptz) RETURNS bigint AS $fn$
      DECLARE removed bigint; last_hash text; last_seq bigint;
      BEGIN
        SELECT count(*), max(seq) INTO removed, last_seq FROM forge_audit WHERE at < before_at AND action <> 'prune';
        IF removed = 0 THEN RETURN 0; END IF;
        SELECT hash INTO last_hash FROM forge_audit WHERE seq = last_seq;
        ALTER TABLE forge_audit DISABLE TRIGGER forge_audit_no_change;
        DELETE FROM forge_audit WHERE at < before_at AND action <> 'prune';
        ALTER TABLE forge_audit ENABLE TRIGGER forge_audit_no_change;
        INSERT INTO forge_audit (action, entity, entity_id, actor_kind, via, after, prev_hash, hash)
        VALUES ('prune', 'forge_audit', NULL, 'system', 'retention',
                jsonb_build_object('removed', removed, 'before', before_at, 'lastSeq', last_seq, 'lastHash', last_hash),
                last_hash, encode(sha256(convert_to(coalesce(last_hash, '') || ':prune:' || removed::text, 'UTF8')), 'hex'));
        RETURN removed;
      END
      $fn$ LANGUAGE plpgsql SECURITY DEFINER;
    `);
    _guarded = true;
  } catch (err) {
    console.warn("[audit] the guard could not be applied (older app or no table yet):", err);
  }
}

/** One row, chained, inside `executor` (a transaction when the caller has one). */
export async function recordAudit(executor: any, entry: AuditEntry): Promise<{ seq: number; hash: string } | null> {
  await policy();
  if (!auditOn()) return null;
  await ensureGuard(executor);
  const at = new Date().toISOString();
  const actor = entry.actor ?? {};
  const actorId = actor.id != null ? String(actor.id) : null;
  const before = _bounded(entry.before);
  const after = _bounded(entry.after);
  const changed = entry.changed ?? (entry.action === "update" ? changedColumns(entry.before, entry.after) : null);
  // ONE ORDER: the lock serialises writers for this transaction, so the
  // previous row is the previous row.
  await executor.execute(sql`SELECT pg_advisory_xact_lock(hashtext(${LOCK_KEY}))`);
  const prev = _rows(await executor.execute(sql`SELECT hash FROM forge_audit ORDER BY seq DESC LIMIT 1`))[0];
  const prevHash: string | null = prev?.hash ?? null;
  const hash = rowHash({ at, actorId, action: entry.action, entity: entry.entity, entityId: entry.entityId ?? null,
    before, after, prevHash });
  // THE CHANGED COLUMNS GO AS JSON, MADE AN ARRAY IN THE QUERY. A list
  // interpolated into the statement is spread into separate values, and
  // Postgres refused every row ("malformed array literal") — a regulated app
  // recorded nothing at all, and only a real database showed it (60v142ju).
  const res = await executor.execute(sql`
    INSERT INTO forge_audit (at, actor_id, actor_role, actor_org_id, actor_kind, via, run_id, action, entity, entity_id,
                             before, after, changed, reason, request_id, ip, user_agent, prev_hash, hash)
    VALUES (${at}::timestamptz, ${actorId}, ${actor.role ?? null}, ${actor.orgId ?? null},
            ${actor.kind ?? (actorId ? "user" : "system")}, ${entry.via ?? "api"}, ${entry.runId ?? null},
            ${entry.action}, ${entry.entity}, ${entry.entityId ?? null},
            ${JSON.stringify(before)}::jsonb, ${JSON.stringify(after)}::jsonb,
            (SELECT array_agg(c) FROM jsonb_array_elements_text(${changed == null ? null : JSON.stringify(changed)}::jsonb) AS t(c)),
            ${entry.reason ?? null}, ${entry.requestId ?? null}, ${entry.ip ?? null},
            ${entry.userAgent ?? null}, ${prevHash}, ${hash})
    RETURNING seq, hash
  `);
  const row = _rows(res)[0];
  return row ? { seq: Number(row.seq), hash: String(row.hash) } : null;
}

/**
 * Run `work` and record what it did, atomically. With no trail declared it
 * is the plain write. `describe` turns the work's result into the entry.
 */
export async function withAudit<T>(
  work: (tx: any) => Promise<T>,
  describe: (result: T) => AuditEntry | null,
): Promise<T> {
  await policy();
  if (!auditOn()) return work(db);
  return db.transaction(async (tx: any) => {
    const result = await work(tx);
    const entry = describe(result);
    if (entry) await recordAudit(tx, entry);
    return result;
  });
}

/** The actor an engine context carries. */
export function actorOf(user: any, guest?: string | null): AuditActor {
  if (user?.id) return { id: String(user.id), role: user.role ? String(user.role) : null,
                         orgId: user.activeOrgId ? String(user.activeOrgId) : null, kind: "user" };
  if (guest) return { id: String(guest), kind: "guest" };
  return { kind: "system" };
}

/** Walk the chain back: every row's hash recomputes, and links to the one before.
 *  `unproven` counts rows written before the canonical hash whose content can
 *  no longer be recomputed (their links are still checked); a canonical row
 *  that does not recompute is a break. */
export async function verifyChain(limit = 100_000): Promise<{ ok: boolean; checked: number; brokenAt?: number; unproven?: number }> {
  await policy();
  const rows = _rows(await db.execute(sql`
    SELECT seq, at, actor_id, action, entity, entity_id, before, after, prev_hash, hash
    FROM forge_audit ORDER BY seq ASC LIMIT ${limit}
  `));
  let prevHash: string | null = null;
  let checked = 0;
  let unproven = 0;
  for (const row of rows) {
    checked += 1;
    if (row.action === "prune") {
      // A prune carries the last hash it kept; the chain resumes from it.
      prevHash = String(row.hash);
      continue;
    }
    const facts = { at: new Date(row.at).toISOString(), actorId: row.actor_id ?? null, action: row.action,
      entity: row.entity, entityId: row.entity_id ?? null, before: row.before ?? null, after: row.after ?? null,
      prevHash: row.prev_hash ?? null };
    if ((row.prev_hash ?? null) !== prevHash) return { ok: false, checked, brokenAt: Number(row.seq) };
    const stored = String(row.hash);
    if (stored.startsWith(HASH_FORM)) {
      if (stored !== rowHash(facts)) return { ok: false, checked, brokenAt: Number(row.seq) };
    } else if (stored !== legacyHash(facts)) {
      unproven += 1;
    }
    prevHash = stored;
  }
  return unproven ? { ok: true, checked, unproven } : { ok: true, checked };
}

/** Rows older than the policy's retention are removed through the one door. */
export async function pruneByPolicy(now: Date = new Date()): Promise<number> {
  await policy();
  const days = Number((AUDIT as any)?.retentionDays ?? 0);
  if (!auditOn() || !(days > 0)) return 0;
  await ensureGuard(db);
  const before = new Date(now.getTime() - days * 86_400_000).toISOString();
  const res = _rows(await db.execute(sql`SELECT forge_audit_prune(${before}::timestamptz) AS removed`))[0];
  return Number(res?.removed ?? 0);
}
