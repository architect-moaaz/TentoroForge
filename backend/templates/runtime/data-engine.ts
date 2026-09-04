/**
 * Data Engine — generic CRUD operations for all entities.
 *
 * Every mutation goes through this engine, which handles:
 * 1. Validation (rules engine)
 * 2. Field-level access control (RBAC)
 * 3. Database operation (Drizzle ORM)
 * 4. Event emission (workflow engine listens)
 *
 * API routes become thin gateways — they call dataEngine.create/update/delete/query.
 */

import { db } from "@/db";
import { eq, ilike, or, and, desc, asc, count, sum, avg, min, max, gte, lt, inArray, sql, getTableName, type SQL } from "drizzle-orm";
// FK-role authority — decides which columns to auto-fill from the current user.
// A `domain` FK (target != users) is NEVER user-filled; only `actor` columns are.
// Absent-table (registry-less app) → legacy name-based fallback below.
import { FK_ROLES, fkRole, isDomainFk } from "./fk-roles";
import type { PgTableWithColumns } from "drizzle-orm/pg-core";
import * as fs from "node:fs";
import * as path from "node:path";
import { windowStart, priorWindow } from "./data-engine/aggregate-window";
// Slice-4 encrypt-at-rest. sensitiveColumnsFor() returns {} for entities
// with no sensitive columns, so every helper below is a no-op fast-path on
// non-sensitive entities — zero overhead for plain CRUD.
import { sensitiveColumnsFor, type SensitiveColumnSpec } from "./sensitive-columns";
import { encryptSensitive, decryptSensitive, mask, looksMasked } from "./sensitive-crypto";
// SEARCH-2 op:"search" — the manifest lists which `_search` tsvector columns
// each entity carries. Empty for apps with no `search: true` columns, so
// resolveSearch fast-paths to [] on the miss.
import { searchableColumnsFor } from "./searchable-columns";
// What to do with a column that names the acting user. Projected from the
// Blueprint's `security.ownershipRules`: a kind:"scope" column decides who may
// reach the row, a kind:"attribution" column only records who acted. Both are
// filled from the session on create; only the first filters. An entity the
// manifest does not mention is unscoped, because the Blueprint declared no
// rule for it — empty for apps that authorise by role alone, so
// scopeConditions() fast-paths to [].
import { ownershipRulesFor, type OwnershipRule } from "./ownership-rules";

/**
 * FK-label expansion. A list row only carries the FK id (a UUID), so a table that
 * binds a column to `memberId` shows a raw UUID. `fk-labels.json` (emitted at
 * generation from the registry) maps each entity's FK columns to their target
 * entity + label field; for every list we batch-resolve those ids to labels and
 * attach a companion `<fkProp>Label` (the real id stays for row actions). Absent /
 * malformed metadata → no expansion, never an error.
 */
type FkMeta = { targetEntity: string; labelField: string };
let _fkMap: Record<string, Record<string, FkMeta>> | null = null;
function fkMap(): Record<string, Record<string, FkMeta>> {
  if (_fkMap) return _fkMap;
  try {
    const p = path.join(process.cwd(), "src", "lib", "fk-labels.json");
    _fkMap = JSON.parse(fs.readFileSync(p, "utf8"));
  } catch {
    _fkMap = {};
  }
  return _fkMap!;
}

async function attachFkLabels(entityName: string, entity: any, rows: any[]): Promise<void> {
  if (!rows || rows.length === 0) return;
  // P1-O11: opt-out for API consumers that don't want `<fkProp>Label` bloat.
  // Set FORGE_FK_LABELS=false to skip label expansion globally (raw ids only).
  // The label expansion still runs by default because table dataSources bind
  // to <fkProp>Label to avoid rendering bare UUIDs.
  if (process.env.FORGE_FK_LABELS === "false") return;
  const all = fkMap();
  // The map is emitted with several aliases per entity (lowercase name, slug,
  // plural slug). Try those; if the route used a friendly name we didn't predict
  // (e.g. "bookings" for ClassBooking), fall back to the entry whose FK columns
  // all exist on the row — an unambiguous shape match.
  let map = all[entityName]
    || all[String(entityName).toLowerCase()]
    || (entity?.slug ? all[entity.slug] : undefined);
  if (!map) {
    const sample = rows[0] || {};
    for (const candidate of Object.values(all)) {
      const props = Object.keys(candidate);
      if (props.length && props.every((k) => k in sample)) { map = candidate; break; }
    }
  }
  if (!map) return;
  for (const [fkProp, meta] of Object.entries(map)) {
    const target = getEntity(meta.targetEntity);
    if (!target || !(target.table as any).id || !(target.table as any)[meta.labelField]) continue;
    const ids = Array.from(new Set(rows.map(r => r[fkProp]).filter(Boolean)));
    if (ids.length === 0) continue;
    try {
      const found = await db
        .select({ id: (target.table as any).id, label: (target.table as any)[meta.labelField] })
        .from(target.table)
        .where(inArray((target.table as any).id, ids as any));
      const byId = new Map(found.map((f: any) => [String(f.id), f.label]));
      for (const r of rows) {
        if (r[fkProp] != null) r[`${fkProp}Label`] = byId.get(String(r[fkProp])) ?? "";
      }
    } catch {
      /* best-effort — a lookup must never break the list */
    }
  }
}

// Types
export interface DataEngineContext {
  /** The acting user. `workspaceId` is read by a scope:"workspace" ownership
   *  rule; a session that does not carry one cannot reach workspace-scoped
   *  rows, which is the safe direction to fail. */
  user?: { id: string; role?: string; email?: string; workspaceId?: string };
  /** Slice-4: original (plaintext) column names the CALLER is explicitly
   *  asking to see unmasked. The route parses `?unmask=col1&unmask=col2`
   *  and passes them here. The read path only honours the request when
   *  the caller's role is in the column's `readers` list — otherwise the
   *  request is silently ignored (mask stays), never a 403. */
  unmaskColumns?: string[];
}

// ─── Slice-4 encrypt-at-rest helpers ─────────────────────────────────────

/** True when the caller's role may unmask this column. Empty readers = nobody
 *  (masked-only, even for admins). "*" wildcard = any authenticated user. */
function _canReaderUnmask(spec: SensitiveColumnSpec, role: string | undefined): boolean {
  if (!spec.readers || spec.readers.length === 0) return false;
  if (spec.readers.includes("*")) return true;
  if (!role) return false;
  return spec.readers.includes(role);
}

/** Structured audit line for every unmask decision the runtime honours.
 *  We deliberately log to console (picked up by Next.js / Vercel / your
 *  log drain) rather than writing to a table here — persisting the audit
 *  event needs an app-specific `forge_audit` schema that Slice 4 does not
 *  ship. Wiring it into that table is a one-line addition later when the
 *  table exists (call db.insert(forgeAudit).values(payload)).
 *  TODO(sensitive-audit-table): persist to forge_audit when the audit
 *  service ships in a future slice. */
function _auditUnmask(entity: string, column: string, ctx: DataEngineContext): void {
  const payload = {
    event: "sensitive_unmask",
    entity,
    column,
    userId: ctx.user?.id ?? null,
    role: ctx.user?.role ?? null,
    timestamp: new Date().toISOString(),
  };
  // JSON on one line keeps this trivially grep-able + parseable by log
  // aggregators. `console.info` is chosen so a debug filter can drop it
  // in dev without losing warnings/errors.
  console.info("[sensitive-unmask]", JSON.stringify(payload));
}

/** Write path: convert every plaintext sensitive value in `data` into the
 *  encrypted + mask column pair the DB actually holds. Idempotent — a
 *  round-tripped masked value (edit form submitted unchanged) is skipped,
 *  never re-encrypted as if it were fresh plaintext. */
async function _encryptSensitiveOnWrite(
  entityName: string,
  data: Record<string, any>,
): Promise<void> {
  const specs = sensitiveColumnsFor(entityName);
  const keys = Object.keys(specs);
  if (keys.length === 0) return;   // no sensitive columns — fast path.
  for (const col of keys) {
    if (!(col in data)) continue;
    const raw = data[col];
    // Empty / undefined = "keep existing" on update, "no value" on create.
    // Either way, we must not overwrite _encrypted / _mask with an empty
    // encrypt (which would blow away the existing sensitive value silently).
    if (raw === undefined || raw === null || raw === "") {
      delete data[col];
      continue;
    }
    // Round-tripped masked value from an edit form → treat as "no change".
    if (looksMasked(raw)) {
      delete data[col];
      continue;
    }
    const spec = specs[col];
    const str = String(raw);
    data[`${col}_encrypted`] = await encryptSensitive(str);
    data[`${col}_mask`] = mask(str, spec.mask);
    delete data[col];  // the plaintext key is never persisted.
  }
}

/** Read path: for every sensitive column on this entity, replace the
 *  `_encrypted` blob with EITHER the pre-computed `_mask` value (default)
 *  OR the decrypted plaintext (when the caller asked to unmask that column
 *  and their role allows it). The `_encrypted` blob itself is ALWAYS
 *  stripped from the response — nothing gains from exposing a ciphertext
 *  the client can't do anything with.
 */
async function _maskOrUnmaskOnRead<T extends Record<string, any>>(
  entityName: string,
  record: T,
  ctx: DataEngineContext,
): Promise<T> {
  const specs = sensitiveColumnsFor(entityName);
  const keys = Object.keys(specs);
  if (keys.length === 0 || record == null) return record;
  const wants = new Set(ctx.unmaskColumns ?? []);
  for (const col of keys) {
    const spec = specs[col];
    const encKey = `${col}_encrypted`;
    const maskKey = `${col}_mask`;
    if (!(encKey in record) && !(maskKey in record)) continue;
    const asked = wants.has(col);
    const allowed = asked && _canReaderUnmask(spec, ctx.user?.role);
    let display: string | null;
    if (allowed) {
      // Honour the unmask — decrypt the blob. A decrypt failure (tampered
      // ciphertext, key rotated without re-encrypt) surfaces the masked
      // value rather than throwing; the audit line is still emitted so
      // the incident is visible in logs.
      const blob = record[encKey];
      _auditUnmask(entityName, col, ctx);
      try {
        display = blob ? await decryptSensitive(String(blob)) : null;
      } catch (e) {
        console.error("[sensitive-unmask] decrypt failed", { entity: entityName, col, e });
        display = record[maskKey] ?? null;
      }
    } else {
      display = record[maskKey] ?? null;
    }
    (record as any)[col] = display;
    // Never leak the ciphertext downstream. Keep `_mask` around — some
    // callers (a Table cell that shows the mask + an eye toggle to
    // request unmask on-demand) rely on the field being labelled as such.
    delete (record as any)[encKey];
  }
  return record;
}


// ─── Row-level scoping ───────────────────────────────────────────────────

/** The actor value a rule compares against, or undefined when we have none. */
function actorValue(rule: OwnershipRule, ctx: DataEngineContext): unknown {
  const v = rule.scope === "workspace"
    ? (ctx.user as any)?.workspaceId
    : ctx.user?.id;
  return v === undefined || v === null || v === "" ? undefined : v;
}

/**
 * The WHERE conditions that limit `entityName` to the rows this actor may reach.
 *
 * Every read and every write funnels through this engine: the catch-all API
 * route calls it, and so does the server render, directly, without passing
 * through that route. That is why the predicate is built here rather than in a
 * route handler — a control on the route would leave every server-rendered
 * list, KPI tile and chart unscoped, which is a longer way of saying unscoped.
 *
 * Only kind:"scope" rules produce a predicate. A kind:"attribution" column
 * records WHO ACTED, not who may look: an ATS fills `createdByUserId` on every
 * candidate and still means every recruiter to see every row, so filtering on
 * it would narrow an application designed to be shared. Both kinds are still
 * filled from the session in create() — the difference is only whether the
 * column also gates reads.
 *
 * Returns [] when the Blueprint declared no scoping rule for the entity. That
 * is the correct answer for an application authorised by role rather than by
 * record, and it is why nothing here infers a rule from a column name.
 *
 * Returns a false predicate — matching nothing — when a rule EXISTS but cannot
 * be applied: no actor on the context, or a column the table does not carry.
 * Both mean the Blueprint and the schema have drifted, and a scoped entity that
 * quietly reverts to unscoped is the failure this whole function exists to
 * prevent, so it fails closed and says so.
 */
function scopeConditions(
  entityName: string,
  entity: { table: PgTableWithColumns<any> },
  ctx: DataEngineContext,
): SQL[] {
  // Tested for "not attribution" rather than "is scope" deliberately: a
  // manifest from an older projection carries no `kind`, and the safe reading
  // of a missing one is that the column scopes.
  const rules: OwnershipRule[] = ownershipRulesFor(entityName)
    .filter((r) => r.kind !== "attribution");
  if (rules.length === 0) return [];
  const role = ctx.user?.role;
  const cols = entity.table as any;
  const conds: SQL[] = [];
  for (const rule of rules) {
    if (role && (rule.unscopedRoles || []).includes(role)) continue;
    const col = cols[rule.column];
    if (col === undefined) {
      console.error(
        `[data-engine] ownership rule for ${entityName} names column ` +
        `"${rule.column}", which the table does not carry — returning no rows ` +
        `rather than every row.`,
      );
      conds.push(sql`false`);
      continue;
    }
    const actor = actorValue(rule, ctx);
    if (actor === undefined) {
      conds.push(sql`false`);
      continue;
    }
    conds.push(eq(col, actor as any));
  }
  return conds;
}

/**
 * The conditions contributed by `row_access` rules — the configurable half.
 *
 * `scopeConditions` above covers what the Blueprint declares structurally: a
 * column that equals the actor. This covers what somebody authored in the
 * rules builder, which is where a rule with a shape nobody anticipated belongs
 * — "readable while it is at offer stage and still active, or where this
 * manager recorded the decision" is not an ownership column, and hard-coding a
 * predicate for it would make the next such rule another code change.
 *
 * Each rule is a GRANT, and grants union: an actor reaches a row if ANY rule
 * addressed to them admits it. A model with rules but none addressed to this
 * actor yields FALSE — the same fail-closed reading `canAccessField` uses, so
 * a role is never handed every row by having been left out.
 *
 * A rule whose condition will not compile to SQL also yields FALSE, loudly. It
 * is the one honest option: evaluating it per row would hide rows from the
 * page while `total`, the pager and every aggregate still counted them.
 */
async function rowAccessConditions(
  entityName: string,
  entity: { table: PgTableWithColumns<any> },
  ctx: DataEngineContext,
): Promise<SQL[]> {
  let rules: Array<{ name?: string; config?: any }>;
  try {
    const { rowAccessRulesFor } = await import("@/lib/rules");
    rules = await rowAccessRulesFor(entityName);
  } catch (e: any) {
    // No rules module is a legitimate app shape — it can hold no row rules, so
    // there is nothing to enforce. A module that THREW is a broken app, and
    // must not be read as one that simply has no rules.
    rethrowIfRulesEngineFailed(e, entityName, "row access");
    return [];
  }
  if (!rules || rules.length === 0) return [];

  const role = ctx.user?.role;
  const applicable = rules.filter((r) => {
    const roles: string[] = r.config?.roles ?? [];
    return roles.length === 0 || (!!role && roles.includes(role));
  });
  if (applicable.length === 0) {
    console.info(
      `[data-engine] ${entityName} has row_access rules but none addressed to ` +
      `role "${role ?? "(none)"}" — no rows.`,
    );
    return [sql`false`];
  }

  const { compileRowAccess } = await import("@/lib/rules/row-access-sql");
  const grants: SQL[] = [];
  for (const rule of applicable) {
    const compiled = compileRowAccess(
      String(rule.config?.whenFeel ?? ""),
      entity.table as any,
      ctx.user as any,
    );
    if (!compiled.ok) {
      console.error(
        `[data-engine] row_access rule "${rule.name ?? "(unnamed)"}" on ` +
        `${entityName} cannot be enforced: ${compiled.reason}. Returning no ` +
        `rows rather than every row.`,
      );
      return [sql`false`];
    }
    grants.push(compiled.where);
  }
  return [grants.length === 1 ? grants[0] : (or(...grants) as SQL)];
}

/**
 * Everything that narrows a read of `entityName` for this actor: what the
 * Blueprint declares as ownership, and what the rules builder declares as row
 * access. One list, so both end up in the same WHERE and the same count.
 */
async function accessConditions(
  entityName: string,
  entity: { table: PgTableWithColumns<any> },
  ctx: DataEngineContext,
): Promise<SQL[]> {
  return [
    ...scopeConditions(entityName, entity, ctx),
    ...(await rowAccessConditions(entityName, entity, ctx)),
  ];
}

/** Fold conditions into one WHERE, or undefined when there are none. */
function allOf(conds: SQL[]): SQL | undefined {
  if (conds.length === 0) return undefined;
  return conds.length === 1 ? conds[0] : (and(...conds) as SQL);
}


export interface QueryOptions {
  search?: string;
  searchFields?: string[];
  filters?: Record<string, string | undefined>;
  sort?: string;
  order?: "asc" | "desc";
  page?: number;
  limit?: number;
}

export interface MutationResult<T = Record<string, any>> {
  data: T;
  event: string;
}

export interface QueryResult<T = Record<string, any>> {
  data: T[];
  total: number;
  page: number;
  limit: number;
}

// Entity registry — populated at startup by reading schema
const _entities: Map<string, {
  table: PgTableWithColumns<any>;
  slug: string;
  searchFields: string[];
}> = new Map();

let _initialized = false;

/**
 * Register an entity with the data engine.
 * Called once at startup for each entity.
 */
export function registerEntity(
  name: string,
  table: PgTableWithColumns<any>,
  opts?: { slug?: string; searchFields?: string[]; aliases?: string[] }
) {
  const columns = Object.keys(table);
  const slug = opts?.slug || name.replace(/([A-Z])/g, "-$1").toLowerCase().replace(/^-/, "");
  const searchFields = opts?.searchFields || columns.filter(c =>
    ["name", "title", "email", "description", "firstName", "lastName"].includes(c)
  );
  const rec = { table, slug, searchFields };
  _entities.set(name.toLowerCase(), rec);
  _entities.set(slug, rec);
  // Register every KNOWN form of this entity as an exact key. `aliases` comes
  // from the canonical resource registry (name / table / slug / camel), so the
  // authority — not a heuristic — declares which strings are this entity. That
  // closes the irregular-plural gap (Person↔people, staff) the fuzzer below
  // cannot bridge. For each form we also index the separator-stripped canonical
  // key (+ its plurality) so a snake export ("recruitment_drives") is reachable
  // from a Pascal/camel query ("RecruitmentDrive" / "recruitmentDrives"), which
  // collapse to "recruitmentdrive(s)" with no underscore.
  for (const raw of [name, slug, ...(opts?.aliases || [])]) {
    const lower = String(raw || "").toLowerCase();
    if (lower && !_entities.has(lower)) _entities.set(lower, rec);
    const c = lower.replace(/[^a-z0-9]/gi, "");
    if (!c) continue;
    if (!_entities.has(c)) _entities.set(c, rec);
    const alt = c.endsWith("s") ? c.slice(0, -1) : c + "s";
    if (!_entities.has(alt)) _entities.set(alt, rec);
  }
}

/**
 * Get the registered entity by name or slug.
 */
function getEntity(nameOrSlug: string) {
  // Schemas reference entities in the SINGULAR ("Property", "RentPayment") but
  // tables are registered under their PLURAL export name ("properties",
  // "rentPayments"). Resolve across kebab/camel AND singular↔plural so the SSR
  // data path + Create/Update workflows find the table either way.
  const base = nameOrSlug.toLowerCase();
  const candidates = new Set<string>([base]);
  candidates.add(nameOrSlug.replace(/-([a-z])/g, (_, c) => c.toUpperCase()).toLowerCase());
  // pluralise
  if (/[^aeiou]y$/.test(base)) candidates.add(base.slice(0, -1) + "ies");
  else if (/(s|x|z|ch|sh)$/.test(base)) candidates.add(base + "es");
  else candidates.add(base + "s");
  // singularise
  if (base.endsWith("ies")) candidates.add(base.slice(0, -3) + "y");
  else if (base.endsWith("es")) candidates.add(base.slice(0, -2));
  if (base.endsWith("s")) candidates.add(base.slice(0, -1));
  // Separator-INSENSITIVE canonical (snake/camel/Pascal/kebab all collapse here),
  // plus its plurality — matches the canonical keys registerEntity indexes.
  const canon = nameOrSlug.replace(/[^a-z0-9]/gi, "").toLowerCase();
  candidates.add(canon);
  if (canon.endsWith("ies")) candidates.add(canon.slice(0, -3) + "y");
  else if (canon.endsWith("es")) candidates.add(canon.slice(0, -2));
  if (canon.endsWith("s")) candidates.add(canon.slice(0, -1));
  else candidates.add(canon + "s");
  for (const key of candidates) {
    const entity = _entities.get(key);
    if (entity) return entity;
  }
  return undefined;
}

// Event bus — workflow engine subscribes to these
type EventHandler = (event: string, payload: any) => void | Promise<void>;
const _listeners: EventHandler[] = [];

export function onDataEvent(handler: EventHandler) {
  _listeners.push(handler);
}

async function emit(event: string, payload: any) {
  for (const handler of _listeners) {
    try {
      await handler(event, payload);
    } catch (e) {
      console.error(`[DataEngine] Event handler error for ${event}:`, e);
    }
  }
}

/**
 * R1: durable event-bus emission — the persistent counterpart to the
 * in-process emit() above. Writes a forge_events row typed
 * "<entitySlug>.created|updated|deleted" and kicks inline processing
 * (event-triggered workflows + wait_for_event resumes).
 *
 * STRICTLY non-fatal and fire-and-forget: a bus failure (missing table on
 * an older app, DB hiccup) must never fail the write that emitted it.
 * Called from the ONE choke point per operation — the tail of
 * create()/update()/remove(), which every CRUD path funnels through.
 */
function _persistEvent(
  op: "created" | "updated" | "deleted",
  entityName: string,
  payload: Record<string, any>,
): void {
  try {
    const slug = String(entityName).toLowerCase();
    void import("./events/bus")
      .then((bus) =>
        bus.emitEventAndProcess(`${slug}.${op}`, {
          entity: slug,
          entityId: payload?.entity?.id != null ? String(payload.entity.id) : null,
          payload,
        }),
      )
      .catch((e) =>
        console.warn(`[DataEngine] event bus emit failed for ${slug}.${op} (non-fatal):`, e),
      );
  } catch (e) {
    console.warn("[DataEngine] event bus emit failed (non-fatal):", e);
  }
}

/**
 * Fire the deferred side effects a business rule requested (trigger_workflow /
 * send_notification) AFTER a successful write. Dispatched onto the same event
 * bus the workflow engine subscribes to; best-effort so a missing subscriber
 * never fails the write.
 */
async function fireRuleEffects(
  effects: Array<{ type: string; workflow?: string; message?: string }>,
  record: any,
  ctx: DataEngineContext,
): Promise<void> {
  for (const eff of effects ?? []) {
    try {
      if (eff.type === "trigger_workflow" && eff.workflow) {
        await emit("rule:trigger_workflow", {
          workflow: eff.workflow,
          entity: record,
          user: ctx.user,
        });
      } else if (eff.type === "send_notification" && eff.message) {
        await emit("rule:notification", {
          message: eff.message,
          entity: record,
          user: ctx.user,
        });
      }
    } catch (e) {
      console.error(`[DataEngine] rule side effect (${eff.type}) failed:`, e);
    }
  }
}

// ─── CRUD Operations ───

/**
 * A container-mode (FormData) KeyValueInput submits its jsonb column as a JSON
 * STRING. Drizzle's json/jsonb columns expect an object/array, so parse any
 * string value destined for a json/jsonb column back into a value before insert.
 * Non-JSON strings and non-json columns are left untouched.
 */
function coerceJsonColumns(table: any, data: Record<string, any>): void {
  for (const [k, v] of Object.entries(data)) {
    if (typeof v !== "string") continue;
    const col = table?.[k];
    const ctype = String(col?.columnType || col?.dataType || "").toLowerCase();
    if (!ctype.includes("json")) continue;
    const s = v.trim();
    if (!(s.startsWith("{") || s.startsWith("["))) continue;
    try { data[k] = JSON.parse(s); } catch { /* leave the raw string */ }
  }
}

// Legacy name-based owner-FK list — used ONLY as a fallback when a table is absent
// from the FK-role authority (registry-less apps). The authoritative path reads roles.
const _LEGACY_OWNER_FKS = ["landlordId", "ownerId", "userId", "createdById", "authorId"];

/**
 * A rules-engine failure must never be mistaken for a rules engine that is
 * simply not installed.
 *
 * A generated app without a rules module is a legitimate configuration. A
 * rules engine that THREW — a bad regex, a malformed rules/index.json, a bug
 * in an expression — is a broken app. Both used to land in the same bare
 * `catch`, so the write proceeded UNVALIDATED with nothing in the logs and a
 * success returned to the caller: every required/pattern/min/max and
 * show_error rule for that entity silently stopped applying.
 *
 * Rethrows anything that is not a missing module, after saying what was lost.
 */
function rethrowIfRulesEngineFailed(e: any, entityName: string, op: string): void {
  const missing =
    e?.code === "MODULE_NOT_FOUND" ||
    e?.code === "ERR_MODULE_NOT_FOUND" ||
    /Cannot find module|Failed to resolve/i.test(String(e?.message ?? ""));
  if (missing) return;
  console.error(
    `[data-engine] rules engine FAILED for ${entityName} ${op} — refusing to ` +
    `write without validation. Every validation and condition_action rule for ` +
    `this entity would otherwise be inert for this write.`,
    e,
  );
  throw e;
}

export async function create(
  entityName: string,
  data: Record<string, any>,
  ctx: DataEngineContext = {}
): Promise<MutationResult> {
  const entity = getEntity(entityName);
  if (!entity) throw new Error(`Unknown entity: ${entityName}`);

  // Strip system / audit fields the DB manages itself.
  const { id, createdAt, updatedAt, created_at, updated_at,
          deletedAt, deleted_at, ...rest } = data;

  // Keep only keys that are real columns on the table — drops hallucinated form
  // fields (e.g. has_gym, year_built) that would otherwise break the insert.
  const cleanData: Record<string, any> = {};
  for (const [k, v] of Object.entries(rest)) {
    if (k in entity.table && v !== "" && v !== undefined) cleanData[k] = v;
  }
  // Default an ACTOR foreign key (a FK to the users table naming who is acting) to
  // the current user when the form didn't collect it. The FK-role authority tells
  // us which columns those are — a `domain` FK (e.g. pets.ownerId → owners) is NEVER
  // filled with the actor's id, which used to cause `*_fk` constraint violations.
  const _uid = ctx.user?.id;
  if (_uid) {
    const _tableName = getTableName(entity.table as any);
    if (_tableName in FK_ROLES) {
      for (const col of Object.keys(entity.table)) {
        if (cleanData[col] != null) continue;
        if (isDomainFk(_tableName, col)) continue;         // never stuff the actor into a domain FK
        if (fkRole(_tableName, col) === "actor") cleanData[col] = _uid;
      }
    } else {
      // No FK-role authority for this table (registry-less app) — preserve the
      // legacy name-based owner-FK fill so those apps don't regress.
      for (const fk of _LEGACY_OWNER_FKS) {
        if (fk in entity.table && cleanData[fk] == null) cleanData[fk] = _uid;
      }
    }
  }
  // Tenancy scoping: fill a NOT NULL workspace/tenant FK server-side (it's no
  // longer a form field) from the user's own workspace, falling back to the
  // single workspace row — so a create still satisfies the NOT NULL constraint.
  const _tenancyFks = ["workspaceId", "tenantId", "orgId", "organizationId"];
  const _needTenancy = _tenancyFks.filter((fk) => fk in entity.table && cleanData[fk] == null);
  if (_needTenancy.length) {
    let _wsId: any = (ctx.user as any)?.workspaceId ?? null;
    if (!_wsId && _uid) {
      try {
        const usersT = getEntity("users")?.table as any;
        if (usersT && "workspaceId" in usersT) {
          const [u] = await db.select().from(usersT).where(eq(usersT.id, _uid)).limit(1);
          _wsId = (u as any)?.workspaceId ?? null;
        }
      } catch { /* ignore — fall back below */ }
    }
    if (!_wsId) {
      for (const wsName of ["workspaces", "workspace", "tenants", "organizations", "orgs"]) {
        const wt = getEntity(wsName)?.table as any;
        if (!wt) continue;
        try {
          const [w] = await db.select().from(wt).limit(1);
          if ((w as any)?.id) { _wsId = (w as any).id; break; }
        } catch { /* ignore */ }
      }
    }
    if (_wsId) for (const fk of _needTenancy) cleanData[fk] = _wsId;
  }

  // Ownership on the write side — BOTH kinds of rule. The column names the
  // acting user, so it is set here and whatever the request body said is
  // discarded. For a scope column that stops a caller planting a row in
  // someone else's account (the read leak in reverse, and invisible to the
  // person it lands on); for an attribution column it is what makes the audit
  // trail mean anything, since a client that can choose its own
  // `createdByUserId` has written a signature, not a record. A role the rule
  // exempts may still file on another's behalf.
  for (const rule of ownershipRulesFor(entityName)) {
    if (ctx.user?.role && (rule.unscopedRoles || []).includes(ctx.user.role)) continue;
    if (!(rule.column in entity.table)) continue;
    const actor = actorValue(rule, ctx);
    // No actor value to write: leave what the tenancy fill above put there
    // rather than nulling a NOT NULL column. A scope column's read path
    // already refuses to return rows this actor cannot claim.
    if (actor === undefined) continue;
    cleanData[rule.column] = actor;
  }

  // jsonb columns arrive as JSON strings from KeyValueInput — parse them back.
  coerceJsonColumns(entity.table, cleanData);

  // Slice-4: rewrite sensitive plaintext values into their _encrypted +
  // _mask column pair BEFORE validation, so rules that reference the
  // sensitive column see the ORIGINAL plaintext (rules are authored
  // against the plan's plaintext column names, not the DB blobs).
  // Note: rules see the plaintext key removed; we save+restore so a rule
  // condition on it still works.
  const _preEncryptSnapshot: Record<string, any> = {};
  for (const col of Object.keys(sensitiveColumnsFor(entityName))) {
    if (col in cleanData) _preEncryptSnapshot[col] = cleanData[col];
  }

  // Validate + apply business rules (if the engine is available).
  let validated = cleanData;
  let ruleEffects: Array<{ type: string; workflow?: string; message?: string }> = [];
  try {
    const { validateEntity, evaluateRuleSet } = await import("@/lib/rules");
    const result = await validateEntity(entityName, cleanData);
    if (!result.valid) {
      throw new ValidationError(result.errors);
    }
    // Condition→action rules: set/default/clear field patches + show_error rejects.
    const rs = await evaluateRuleSet(entityName, "create", cleanData, ctx.user);
    if (rs.errors.length) {
      throw new ValidationError(rs.errors);
    }
    validated = { ...cleanData, ...rs.patches };
    ruleEffects = rs.sideEffects;
  } catch (e: any) {
    if (e instanceof ValidationError) throw e;
    rethrowIfRulesEngineFailed(e, entityName, "create");
  }

  // Now perform the encrypt/mask rewrite on the post-rules payload — rules
  // may have PATCHED a sensitive value (e.g. normalised whitespace on an
  // SSN); we encrypt the final value, not the pre-rules snapshot.
  for (const [k, v] of Object.entries(_preEncryptSnapshot)) {
    if (validated[k] === undefined) validated[k] = v;
  }
  await _encryptSensitiveOnWrite(entityName, validated);

  // Insert
  const [record] = await db.insert(entity.table).values(validated as any).returning();
  const event = `${entityName.toLowerCase()}_created`;

  // Emit event for workflow engine
  emit(event, { entityId: record.id, entity: record, user: ctx.user }).catch(console.error);
  // R1: durable bus row ("<slug>.created") — non-fatal, fire-and-forget.
  _persistEvent("created", entityName, { entity: record, user: ctx.user });
  // Fire rule side effects (trigger_workflow / send_notification) after the write.
  fireRuleEffects(ruleEffects, record, ctx).catch(console.error);

  // Never return the raw ciphertext; mask or unmask per Slice-4 read policy.
  await _maskOrUnmaskOnRead(entityName, record, ctx);
  return { data: record, event };
}

export async function update(
  entityName: string,
  id: string,
  data: Record<string, any>,
  ctx: DataEngineContext = {}
): Promise<MutationResult> {
  const entity = getEntity(entityName);
  if (!entity) throw new Error(`Unknown entity: ${entityName}`);

  // Check exists — scoped, so a row belonging to someone else is NotFound
  // rather than editable. The same predicate is reused on the UPDATE below:
  // checking here and writing unscoped would leave a race between them.
  const where = allOf([eq(entity.table.id, id),
                       ...await accessConditions(entityName, entity, ctx)])!;
  const [existing] = await db.select().from(entity.table).where(where).limit(1);
  if (!existing) throw new NotFoundError(entityName, id);

  // Strip system fields
  const { id: _, createdAt, updatedAt, created_at, updated_at, ...cleanData } = data;

  // jsonb columns arrive as JSON strings from KeyValueInput — parse them back.
  coerceJsonColumns(entity.table, cleanData);

  // Validate + apply business rules over the merged row.
  let ruleEffects: Array<{ type: string; workflow?: string; message?: string }> = [];
  let patched = cleanData;
  try {
    const { validateEntity, evaluateRuleSet } = await import("@/lib/rules");
    const merged = { ...existing, ...cleanData };
    const result = await validateEntity(entityName, merged);
    if (!result.valid) {
      throw new ValidationError(result.errors);
    }
    const rs = await evaluateRuleSet(entityName, "update", merged, ctx.user);
    if (rs.errors.length) {
      throw new ValidationError(rs.errors);
    }
    // Only patch keys the rules actually set (don't rewrite the whole row).
    patched = { ...cleanData, ...rs.patches };
    ruleEffects = rs.sideEffects;
  } catch (e: any) {
    if (e instanceof ValidationError) throw e;
    rethrowIfRulesEngineFailed(e, entityName, "update");
  }

  // Slice-4: encrypt any sensitive plaintext value in the payload. The
  // helper skips empty/undefined + round-tripped mask values, so an edit
  // form that pre-filled with the masked read (and left it unchanged)
  // will NOT clobber the existing ciphertext.
  const updateData = { ...patched, updatedAt: new Date() } as any;
  await _encryptSensitiveOnWrite(entityName, updateData);

  const [record] = await db.update(entity.table).set(updateData).where(where).returning();
  const event = `${entityName.toLowerCase()}_updated`;

  emit(event, { entityId: record.id, entity: record, previousEntity: existing, user: ctx.user }).catch(console.error);
  // R1: durable bus row ("<slug>.updated") — non-fatal, fire-and-forget.
  _persistEvent("updated", entityName, { entity: record, previousEntity: existing, user: ctx.user });
  fireRuleEffects(ruleEffects, record, ctx).catch(console.error);

  await _maskOrUnmaskOnRead(entityName, record, ctx);
  return { data: record, event };
}

export async function remove(
  entityName: string,
  id: string,
  ctx: DataEngineContext = {}
): Promise<MutationResult> {
  const entity = getEntity(entityName);
  if (!entity) throw new Error(`Unknown entity: ${entityName}`);

  const where = allOf([eq(entity.table.id, id),
                       ...await accessConditions(entityName, entity, ctx)])!;
  const [existing] = await db.select().from(entity.table).where(where).limit(1);
  if (!existing) throw new NotFoundError(entityName, id);

  await db.delete(entity.table).where(where);
  const event = `${entityName.toLowerCase()}_deleted`;

  emit(event, { entityId: id, entity: existing, user: ctx.user }).catch(console.error);
  // R1: durable bus row ("<slug>.deleted") — non-fatal, fire-and-forget.
  _persistEvent("deleted", entityName, { entity: existing, user: ctx.user });

  return { data: existing, event };
}

export async function findById(
  entityName: string,
  id: string,
  ctx: DataEngineContext = {}
): Promise<Record<string, any>> {
  const entity = getEntity(entityName);
  if (!entity) throw new Error(`Unknown entity: ${entityName}`);

  // The ownership predicate rides in the WHERE, so a row belonging to someone
  // else is NotFound rather than Forbidden — the caller cannot tell an id that
  // does not exist from one they may not see, which is what stops a detail
  // route from being an existence oracle.
  const where = allOf([eq(entity.table.id, id),
                       ...await accessConditions(entityName, entity, ctx)])!;
  const [record] = await db.select().from(entity.table).where(where).limit(1);
  if (!record) throw new NotFoundError(entityName, id);

  // Slice-4: mask or unmask sensitive columns before we hand the record to
  // the rules-based field-level filter (which never sees the ciphertext).
  await _maskOrUnmaskOnRead(entityName, record, ctx);

  // Apply field-level read access
  try {
    const { filterFields } = await import("@/lib/rules");
    return await filterFields(entityName, record, { role: ctx.user?.role });
  } catch {
    return record;
  }
}

export async function query(
  entityName: string,
  opts: QueryOptions = {},
  ctx: DataEngineContext = {}
): Promise<QueryResult> {
  const entity = getEntity(entityName);
  if (!entity) throw new Error(`Unknown entity: ${entityName}`);

  const { search, filters, sort, order = "desc", page = 1, limit = 50 } = opts;
  const offset = (page - 1) * limit;

  // ONE condition list, shared by the row query and the count. Drizzle's
  // .where() REPLACES a previous call rather than ANDing with it, so the old
  // form — .where(search) then .where(filters) — silently dropped the search
  // whenever a filter was also present. Collecting the conditions and applying
  // them once removes the failure mode rather than ordering around it.
  const conditions: SQL[] = await accessConditions(entityName, entity, ctx);

  // Search — the OR across search fields is ONE condition, so it ANDs with the
  // filters and with the ownership predicate instead of competing with them.
  if (search && entity.searchFields.length > 0) {
    const searchConditions = entity.searchFields
      .filter(f => entity.table[f])
      .map(f => ilike(entity.table[f], `%${search}%`));
    if (searchConditions.length > 0) {
      conditions.push(or(...searchConditions) as SQL);
    }
  }

  // Filters
  if (filters) {
    for (const [key, value] of Object.entries(filters)) {
      if (value && value !== "undefined" && entity.table[key]) {
        conditions.push(eq(entity.table[key], value));
      }
    }
  }

  const where = allOf(conditions);

  let q: any = db.select().from(entity.table);
  if (where) q = q.where(where);

  // Sort
  const sortCol = sort && entity.table[sort] ? entity.table[sort] : entity.table.createdAt;
  if (sortCol) {
    q = q.orderBy(order === "asc" ? asc(sortCol) : desc(sortCol));
  }

  // Count — over the SAME where. It used to count the whole table, so a
  // filtered or searched list reported the unfiltered total and the pager
  // offered pages that returned nothing.
  let countQ: any = db.select({ total: count() }).from(entity.table);
  if (where) countQ = countQ.where(where);
  const [countResult] = await countQ;
  const total = countResult?.total ?? 0;

  // Paginate
  const data = await q.limit(limit).offset(offset);

  // Slice-4: mask/unmask sensitive columns per row before rules-based
  // field filtering. Rows never expose ciphertext to the client.
  await Promise.all(data.map((r: any) => _maskOrUnmaskOnRead(entityName, r, ctx)));

  // Apply field-level read access
  let filtered = data;
  try {
    const { filterFields } = await import("@/lib/rules");
    filtered = await Promise.all(
      data.map((r: any) => filterFields(entityName, r, { role: ctx.user?.role }))
    );
  } catch {
    // Rules not available
  }

  // Resolve FK ids → their referenced record's label (memberId → "Alice Johnson"),
  // attached as `<fkProp>Label` so tables can show names instead of raw UUIDs.
  await attachFkLabels(entityName, entity, filtered);

  return { data: filtered, total, page, limit };
}

export async function stats(
  entityName: string,
  ctx: DataEngineContext = {},
): Promise<{ total: number }> {
  const entity = getEntity(entityName);
  if (!entity) throw new Error(`Unknown entity: ${entityName}`);

  // Scoped like the list it summarises. An unscoped count is a row count of
  // everyone's data wearing a number badge.
  const where = allOf(await accessConditions(entityName, entity, ctx));
  let q: any = db.select({ total: count() }).from(entity.table);
  if (where) q = q.where(where);
  const [result] = await q;
  return { total: result?.total ?? 0 };
}

// ─── Aggregate Resolver ───

/** A plain aggregate metric — one Drizzle fn over an (optionally windowed,
 *  optionally filtered) entity. Returns a single number. */
type SimpleMetric = {
  fn: "count" | "sum" | "avg" | "min" | "max";
  field?: string;
  entity?: string;
  window?: "today" | "week" | "month";
  dateField?: string;
  filter?: Record<string, unknown>;
};

/** ratio metric — numerator / denominator (e.g. cache hits / total requests).
 *  `percent:true` returns 0-100 instead of a 0-1 fraction. Div-by-zero → 0. */
type RatioMetric = {
  kind: "ratio";
  entity?: string;                 // default entity for both sub-metrics
  numerator: SimpleMetric;
  denominator: SimpleMetric;
  percent?: boolean;
};

/** period-delta metric — this window vs the immediately-preceding one (e.g.
 *  "↑ 40% vs last month"). `percent:true` → % change; else the absolute delta.
 *  Prior-period value of 0 → 0 (avoids Infinity). */
type DeltaMetric = {
  kind: "delta";
  fn: "count" | "sum" | "avg" | "min" | "max";
  field?: string;
  entity?: string;
  window: "today" | "week" | "month";   // required — a delta needs a period
  dateField?: string;
  filter?: Record<string, unknown>;
  percent?: boolean;
};

/** Metric descriptor on an op:"aggregate" dataSource. A plain object with no
 *  `kind` is a SimpleMetric (backward compatible). */
type Metric = SimpleMetric | RatioMetric | DeltaMetric;

/** Shape of an op:"aggregate" dataSource in a page schema. */
type AggregateSource = {
  name: string;
  entity: string;
  op: "aggregate";
  metrics?: Record<string, Metric>;
};

/** Test seam: override the db handle inside resolveAggregate for unit tests.
 *  Call __setTestDb(null) to restore. Never used in production code paths. */
let _testDb: any = null;
export function __setTestDb(d: any) { _testDb = d; }

/** Run a single plain aggregate and return a number (0 on missing entity / error).
 *  `range` overrides the metric's own `window` with an explicit half-open
 *  [start, end) — used by period-delta to query the prior window. */
async function computeSimple(
  defaultEntity: string,
  m: SimpleMetric,
  ctx: DataEngineContext,
  range?: { start?: Date | null; end?: Date | null },
): Promise<number> {
  const entityName = m.entity || defaultEntity;
  const entity = getEntity(entityName);
  if (!entity) return 0;

  // sum/avg/min/max need a real column; a misconfigured metric without one
  // degrades to 0 rather than building an invalid query.
  if (m.fn !== "count" && !m.field) return 0;

  const cols = entity.table as any;

  // Build the aggregate expression — count() needs no column; others need m.field.
  const agg =
    m.fn === "count" ? count() :
    m.fn === "sum"   ? sum(cols[m.field!]) :
    m.fn === "avg"   ? avg(cols[m.field!]) :
    m.fn === "min"   ? min(cols[m.field!]) :
                       max(cols[m.field!]);

  // Accumulate WHERE conditions (ownership + window / explicit range + filters).
  // A KPI tile is a read like any other: "12 open invoices" computed over every
  // tenant's invoices is the same leak as listing them, one integer at a time.
  const conds: SQL[] = await accessConditions(entityName, entity, ctx);
  const dateCol = cols[m.dateField || "createdAt"];
  const start = range ? range.start : windowStart(m.window);
  if (start && dateCol) conds.push(gte(dateCol, start));
  if (range?.end && dateCol) conds.push(lt(dateCol, range.end));
  for (const [k, v] of Object.entries(m.filter || {})) {
    if (cols[k] !== undefined) conds.push(eq(cols[k], v as any));
  }

  const _db = _testDb ?? db;
  let q = (_db as any).select({ value: agg }).from(entity.table);
  if (conds.length) q = q.where(conds.length === 1 ? conds[0] : and(...conds));
  const [row] = await q;
  // sum/avg return string | null from Drizzle; Number() normalises all variants.
  return Number(row?.value ?? 0);
}

/** Resolve one metric (simple | ratio | delta) to a number. Any failure → 0. */
async function computeMetric(
  defaultEntity: string,
  m: Metric,
  ctx: DataEngineContext,
): Promise<number> {
  // ratio — numerator / denominator (× 100 when percent). Div-by-zero → 0.
  if ((m as RatioMetric).kind === "ratio") {
    const r = m as RatioMetric;
    const ent = r.entity || defaultEntity;
    const [num, den] = await Promise.all([
      computeSimple(ent, r.numerator, ctx),
      computeSimple(ent, r.denominator, ctx),
    ]);
    if (!den) return 0;
    const ratio = num / den;
    return r.percent ? ratio * 100 : ratio;
  }

  // period-delta — this window vs the immediately-preceding one.
  if ((m as DeltaMetric).kind === "delta") {
    const d = m as DeltaMetric;
    const ent = d.entity || defaultEntity;
    const base: SimpleMetric = {
      fn: d.fn, field: d.field, entity: ent, dateField: d.dateField, filter: d.filter,
    };
    const prior = priorWindow(d.window);
    const [cur, prev] = await Promise.all([
      computeSimple(ent, { ...base, window: d.window }, ctx),
      computeSimple(ent, base, ctx, prior ?? { start: null, end: null }),
    ]);
    if (d.percent) return prev === 0 ? 0 : ((cur - prev) / prev) * 100;
    return cur - prev;
  }

  // plain aggregate (backward compatible — no `kind`).
  return computeSimple(defaultEntity, m as SimpleMetric, ctx);
}

/**
 * Resolve an op:"aggregate" dataSource into a flat { metricKey: number } object.
 *
 * Mirrors the real stats() Drizzle pattern. Each failing metric degrades to 0 —
 * the page never blanks or shows a literal {{…}} binding.
 */
export async function resolveAggregate(
  source: AggregateSource,
  ctx: DataEngineContext = {},
): Promise<Record<string, number>> {
  const out: Record<string, number> = {};
  const metrics = source.metrics || {};
  await Promise.all(
    Object.entries(metrics).map(async ([key, m]) => {
      try {
        out[key] = await computeMetric(source.entity, m, ctx);
      } catch {
        out[key] = 0;
      }
    })
  );
  return out;
}

// ─── Series Resolver (op:"series") ───

/** Shape of an op:"series" dataSource — a grouped aggregate that returns an
 *  ARRAY of { label, value } rows for charts (as opposed to op:"aggregate",
 *  which returns one flat { metricKey: number } object for KPI tiles). */
type SeriesSource = {
  name: string;
  entity: string;
  op: "series";
  // groupBy is required for aggregate fns (count/sum/avg/min/max) — the SQL
  // GROUP BY column. IGNORED when agg.fn is "running_sum" (running series
  // returns one row per source row, ordered by orderByCol below).
  groupBy?: string;
  bucket?: "day" | "week" | "month";  // set when groupBy is a date/timestamp column
  agg?: {
    // Slice-3 ledger: "running_sum" is a stateful per-row cumulative aggregate
    // (SUM(field) OVER (ORDER BY orderByCol)). Every other fn is a standard
    // GROUP BY.
    fn: "count" | "sum" | "avg" | "min" | "max" | "running_sum";
    field?: string;
  };
  // Order column for running_sum only. Defaults to "createdAt" (every entity
  // ships with one), which is also the natural insertion order for a ledger.
  orderByCol?: string;
  filter?: Record<string, unknown>;
  sort?: "label" | "value";           // default: label (chronological for date buckets)
  limit?: number;
};

const _SERIES_BUCKETS = new Set(["day", "week", "month"]);

/** Format a group value for the chart's x-axis. Date buckets → short readable
 *  strings; everything else → the raw value coerced to a string. */
function formatSeriesLabel(v: unknown, bucket?: string): string {
  if (v === null || v === undefined) return "—";
  if (bucket) {
    const d = v instanceof Date ? v : new Date(v as any);
    if (!isNaN(d.getTime())) {
      return bucket === "month"
        ? d.toLocaleDateString("en-US", { month: "short", year: "numeric" })
        : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    }
  }
  return String(v);
}

/**
 * Resolve an op:"series" dataSource into an array of { label, value } rows via a
 * real SQL GROUP BY. Two modes:
 *   • category  — groupBy a normal column (e.g. status, priority)
 *   • time      — groupBy a date column + bucket:"day"|"week"|"month"
 *                 (compiled to Postgres date_trunc)
 * Charts bind `data: "{{sourceName}}"` with xKey:"label" and
 * series:[{ dataKey:"value" }]. Any failure degrades to [] so the chart shows
 * its empty state rather than a literal {{…}} binding — never blanks the page.
 */
export async function resolveSeries(
  source: SeriesSource,
  ctx: DataEngineContext = {},
): Promise<Array<{ label: string; value: number }>> {
  const entity = getEntity(source.entity);
  if (!entity) return [];
  const cols = entity.table as any;
  // A chart is a read. A revenue-by-month series over every tenant's rows
  // leaks the same data a list would, aggregated into a shape that looks
  // harmless.
  const scope = await accessConditions(source.entity, entity, ctx);

  const fn = source.agg?.fn || "count";

  // Slice-3 ledger: running_sum is a stateful per-row cumulative aggregate.
  // Not a GROUP BY — one output row per source row, ordered by orderByCol
  // (defaults to createdAt). The client uses it to render a running-balance
  // column alongside the raw transaction table.
  if (fn === "running_sum") {
    const fld = source.agg?.field;
    if (!fld || cols[fld] === undefined) return [];
    const orderName = source.orderByCol || "createdAt";
    const orderCol = cols[orderName];
    if (orderCol === undefined) return [];
    const conds: SQL[] = [...scope];
    for (const [k, v] of Object.entries(source.filter || {})) {
      if (cols[k] !== undefined) conds.push(eq(cols[k], v as any));
    }
    try {
      const _db = _testDb ?? db;
      // SUM(field) OVER (ORDER BY orderCol) — one running total per row.
      // Kept as `sql` fragment because drizzle doesn't model window fns yet.
      const running = sql<number>`SUM(${cols[fld]}) OVER (ORDER BY ${orderCol})`;
      let q = (_db as any).select({ label: orderCol, value: running }).from(entity.table);
      if (conds.length) q = q.where(conds.length === 1 ? conds[0] : and(...conds));
      q = q.orderBy(orderCol);
      const rows: Array<{ label: unknown; value: unknown }> = await q;
      const out = rows.map((r) => ({
        // Format the anchor column: date-shaped columns get short-form dates,
        // everything else stringifies. The label doubles as the join key the
        // client uses when interleaving running values into the row list.
        label: formatSeriesLabel(r.label, undefined),
        value: Number(r.value ?? 0),
      }));
      return source.limit && source.limit > 0 ? out.slice(0, source.limit) : out;
    } catch {
      return [];
    }
  }

  const groupCol = cols[source.groupBy as string];
  if (groupCol === undefined) return [];

  // sum/avg/min/max need a real column that exists on the table.
  if (fn !== "count" && (!source.agg?.field || cols[source.agg.field] === undefined)) return [];

  const aggExpr =
    fn === "count" ? count() :
    fn === "sum"   ? sum(cols[source.agg!.field!]) :
    fn === "avg"   ? avg(cols[source.agg!.field!]) :
    fn === "min"   ? min(cols[source.agg!.field!]) :
                     max(cols[source.agg!.field!]);

  // Group expression: a whitelisted date_trunc bucket, or the raw column.
  const bucket = source.bucket && _SERIES_BUCKETS.has(source.bucket) ? source.bucket : undefined;
  const labelExpr: any = bucket ? sql`date_trunc(${bucket}, ${groupCol})` : groupCol;

  const conds: SQL[] = [...scope];
  for (const [k, v] of Object.entries(source.filter || {})) {
    if (cols[k] !== undefined) conds.push(eq(cols[k], v as any));
  }

  try {
    const _db = _testDb ?? db;
    let q = (_db as any).select({ label: labelExpr, value: aggExpr }).from(entity.table);
    if (conds.length) q = q.where(conds.length === 1 ? conds[0] : and(...conds));
    q = q.groupBy(labelExpr);
    const rows: Array<{ label: unknown; value: unknown }> = await q;

    let out = rows.map((r) => ({
      label: formatSeriesLabel(r.label, bucket),
      value: Number(r.value ?? 0),
      _raw: r.label,
    }));

    // Ordering: "value" → descending magnitude (category rankings); otherwise by
    // key — chronological for date buckets (sort the raw timestamps), else alpha.
    if (source.sort === "value") {
      out.sort((a, b) => b.value - a.value);
    } else if (bucket) {
      out.sort((a, b) => {
        const da = new Date(a._raw as any).getTime();
        const db2 = new Date(b._raw as any).getTime();
        return (isNaN(da) ? 0 : da) - (isNaN(db2) ? 0 : db2);
      });
    } else {
      out.sort((a, b) => a.label.localeCompare(b.label));
    }

    const trimmed = source.limit && source.limit > 0 ? out.slice(0, source.limit) : out;
    return trimmed.map(({ label, value }) => ({ label, value }));
  } catch {
    return [];
  }
}

// ─── Search Resolver (op:"search") ───

/** Shape of an op:"search" dataSource — a full-text search across one or
 *  more entities' `_search` tsvector columns. Emitted by schema_builder for
 *  every column flagged `search: true`. Multi-entity search is first-class:
 *  results are ts_rank-merged across entities and capped at `limit`.
 *
 *  columns  — optional restriction to specific searchable columns; defaults
 *             to every searchable column on the entity per the manifest.
 *  snippet  — when true (default), ts_headline returns the matched snippet
 *             with `<b>…</b>` highlights around hits.
 *  limit    — cap on total results after cross-entity merge. Defaults to 20.
 */
type SearchSource = {
  name: string;
  op: "search";
  entities: string[];
  q: string;
  columns?: string[];
  snippet?: boolean;
  limit?: number;
};

/** A single search hit. `entity` is the ORIGINAL entity name the caller
 *  passed on `entities[]`. `snippet` is HTML (safe — Postgres ts_headline
 *  emits `<b>…</b>` markup only). Extra primary-field props on the row are
 *  spread — the caller decides which to render. */
type SearchHit = {
  id: unknown;
  entity: string;
  snippet: string;
  rank: number;
  [key: string]: unknown;
};

const _SEARCH_DEFAULT_LIMIT = 20;

/**
 * Resolve an op:"search" dataSource to a ranked list of hits across every
 * entity in ``source.entities``. Uses the `_search` tsvector columns +
 * plainto_tsquery + ts_rank; ts_headline emits the snippet unless
 * ``snippet:false`` (skips the headline call — faster on huge queries).
 *
 * Empty query → []. Unknown entity → skipped silently (never errors).
 * Any single-entity query failure degrades to [] for THAT entity; other
 * entities in the batch still return their rows.
 *
 * All user input rides through parameter binding — no string concat, no
 * SQL injection surface. `plainto_tsquery` handles the tsquery escaping.
 */
export async function resolveSearch(
  source: SearchSource,
  ctx: DataEngineContext = {},
): Promise<SearchHit[]> {
  const q = String(source.q ?? "").trim();
  if (!q) return [];
  const entities = Array.isArray(source.entities) ? source.entities : [];
  if (entities.length === 0) return [];
  const wantSnippet = source.snippet !== false;
  const limit = source.limit && source.limit > 0 ? source.limit : _SEARCH_DEFAULT_LIMIT;

  const _db = _testDb ?? db;

  const perEntityRows = await Promise.all(entities.map(async (entityName): Promise<SearchHit[]> => {
    const entity = getEntity(entityName);
    if (!entity) return [];
    const cols = entity.table as any;

    // Which `_search` columns does this entity carry? The runtime manifest
    // is the authority — never guess.
    const allSearchable = searchableColumnsFor(entityName);
    if (allSearchable.length === 0) return [];
    const wanted = Array.isArray(source.columns) && source.columns.length > 0
      ? source.columns.filter((c) => allSearchable.includes(c))
      : allSearchable;
    if (wanted.length === 0) return [];

    // Pick a primary display column: the first searchable column that
    // exists on the table. Callers get {id, snippet, rank, <primary>: value}.
    const primaryCol = wanted.find((c) => cols[c] !== undefined) || wanted[0];

    // Build the tsvector expression: OR the requested `_search` columns
    // together so a single tsquery match on any covered column returns
    // the row. Skips columns the drizzle table doesn't carry (registry
    // drift safety — never blow up).
    const vectorCols = wanted
      .map((c) => cols[`${c}_search`])
      .filter((v) => v !== undefined);
    if (vectorCols.length === 0) return [];

    // Combine multiple _search columns via ||. Single-column path avoids
    // the concat.
    const vectorExpr = vectorCols.length === 1
      ? sql`${vectorCols[0]}`
      : sql.join(vectorCols.map((v: any) => sql`${v}`), sql` || `);

    // `plainto_tsquery` — treats `q` as a plain phrase; escapes operators;
    // safe with any user input via parameter binding.
    const tsq = sql`plainto_tsquery('english', ${q})`;
    const rankExpr = sql<number>`ts_rank(${vectorExpr}, ${tsq})`;

    // Snippet — ts_headline over the PRIMARY plaintext column (not the
    // tsvector — headline needs the original text). Falls back to empty
    // string when the caller opted out.
    const primaryPlainCol = cols[primaryCol];
    const snippetExpr = wantSnippet && primaryPlainCol !== undefined
      ? sql<string>`ts_headline('english', coalesce(${primaryPlainCol}, ''), ${tsq})`
      : sql<string>`''`;

    // Ownership predicate first — a search that matches rows the caller may
    // not read hands them the contents a snippet at a time.
    const conds: SQL[] = [
      sql`${vectorExpr} @@ ${tsq}`,
      ...await accessConditions(entityName, entity, ctx),
    ];
    for (const [k, v] of Object.entries(source.filter || {})) {
      if (cols[k] !== undefined) conds.push(eq(cols[k], v as any));
    }

    try {
      const selectShape: Record<string, any> = {
        id: cols.id,
        rank: rankExpr,
        snippet: snippetExpr,
      };
      // Include the primary column value when the column exists on the
      // table so callers can render a title without a second query.
      if (primaryPlainCol !== undefined) {
        selectShape[primaryCol] = primaryPlainCol;
      }
      let qb = (_db as any).select(selectShape).from(entity.table);
      qb = qb.where(conds.length === 1 ? conds[0] : and(...conds));
      qb = qb.orderBy(desc(rankExpr));
      // Cap per-entity to the total limit so the merge below has a small
      // window to sort — a page of 20 total from 3 entities never needs
      // >20 rows from any one entity.
      qb = qb.limit(limit);
      const rows: any[] = await qb;
      return rows.map((r) => ({
        id: r.id,
        entity: entityName,
        snippet: String(r.snippet ?? ""),
        rank: Number(r.rank ?? 0),
        ...(primaryPlainCol !== undefined ? { [primaryCol]: r[primaryCol] } : {}),
      }));
    } catch {
      return [];
    }
  }));

  // Merge + rank-sort + cap. Ranking is by ts_rank descending — matches the
  // per-entity ORDER BY so a same-entity block stays grouped by relevance.
  const merged = perEntityRows.flat();
  merged.sort((a, b) => b.rank - a.rank);
  return merged.slice(0, limit);
}

// ─── Error Classes ───

export class ValidationError extends Error {
  errors: string[];
  constructor(errors: string[]) {
    super(errors.join(", "));
    this.name = "ValidationError";
    this.errors = errors;
  }
}

export class NotFoundError extends Error {
  constructor(entity: string, id: string) {
    super(`${entity} with id ${id} not found`);
    this.name = "NotFoundError";
  }
}

// ─── Initialization ───

export function isInitialized() {
  return _initialized;
}

export function markInitialized() {
  _initialized = true;
}

// ── Wave 5 Extensions: Aggregations + Saved Views + Cursor Pagination ──

// Import aggregation helpers (generated apps import from the data-engine subdir)
import type { AggregationQuery } from "./data-engine/aggregations";

/**
 * Route handler stub: POST /api/data/{table}/aggregate
 *
 * Body shape:
 *   { fn: "count"|"sum"|"avg"|"min"|"max", field?: string,
 *     groupBy?: string[], filter?: Record<string, any> }
 *
 * The actual executeAggregation is in data-engine/aggregations.ts — generated
 * apps import it directly. This stub shows the intended route signature.
 */
export async function handleAggregate(table: string, body: any) {
  const { executeAggregation } = await import("./data-engine/aggregations");
  const query: AggregationQuery = {
    table,
    fn: body.fn,
    field: body.field,
    groupBy: body.groupBy,
    filter: body.filter,
  };
  return executeAggregation(db, query);
}

// ─── Cursor-based Pagination ───

interface ListQuery {
  table: string;
  filter?: Record<string, any>;
  sortBy?: { field: string; direction: "asc" | "desc" };
  cursor?: string;         // base64-encoded last-item key
  limit?: number;          // default 50, max 200
}

/**
 * Paginate a table using cursor-based pagination.
 *
 * NOTE: This is a sketch for Drizzle ORM. Adapt to the actual ORM in use.
 * The cursor is a base64-encoded JSON string of the last row's ID.
 */
export async function handleListPaginated(table: string, query: ListQuery) {
  const limit = Math.min(query.limit ?? 50, 200);
  let qb = (db as any).select().from((db as any)[table]);
  if (query.filter) {
    for (const [k, v] of Object.entries(query.filter)) {
      qb = qb.where((db as any)[table][k].eq(v));
    }
  }
  if (query.sortBy) {
    qb = qb.orderBy((db as any)[table][query.sortBy.field][query.sortBy.direction]());
  }
  if (query.cursor) {
    const lastKey = JSON.parse(atob(query.cursor));
    qb = qb.where((db as any)[table].id.gt(lastKey));   // assumes ID-based cursor
  }
  qb = qb.limit(limit + 1);  // +1 to detect hasMore

  const rows = await qb;
  const hasMore = rows.length > limit;
  const visible = rows.slice(0, limit);
  const nextCursor = hasMore ? btoa(JSON.stringify(visible[visible.length - 1].id)) : null;
  return { rows: visible, nextCursor, hasMore };
}
