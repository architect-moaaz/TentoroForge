/**
 * The organisations a person belongs to, and the one they act in.
 *
 * `TENANCY` is projected from the Blueprint (`src/lib/tenancy-policy.ts`;
 * none for an application with one organisation). A membership gives a
 * person their role IN an organisation; a platform role is held everywhere
 * and sees every organisation. The active organisation is
 * `users.active_org_id`, set at signup, on an invite, or by switching.
 */
import { sql } from "drizzle-orm";
import { db } from "@/db";

export interface TenancyPolicy {
  kind: "none" | "organisation";
  entity: string | null;
  table: string | null;
  nameColumn: string | null;
  memberRoles: string[];
  platformRoles: string[];
  adminRole: string | null;
  signup: "creates_organisation" | "joins_by_invite" | "both";
  /** The tenancy column per table that belongs to an organisation. */
  columns: Record<string, string>;
}

let POLICY: TenancyPolicy = { kind: "none", entity: null, table: null, nameColumn: null, memberRoles: [], platformRoles: [],
  adminRole: null, signup: "both", columns: {} };
let _loaded = false;

export async function policy(): Promise<TenancyPolicy> {
  if (_loaded) return POLICY;
  _loaded = true;
  try {
    const mod: any = await import("./tenancy-policy");
    if (mod?.TENANCY) POLICY = { ...POLICY, ...mod.TENANCY };
  } catch { /* none projected */ }
  return POLICY;
}

export function tenancyOn(): boolean {
  return POLICY.kind === "organisation";
}

function _rows(res: unknown): any[] {
  return Array.isArray(res) ? res : ((res as { rows?: any[] })?.rows ?? []);
}

export interface Membership { orgId: string; role: string; orgName?: string | null }

export async function membershipsOf(userId: string): Promise<Membership[]> {
  await policy();
  if (!tenancyOn()) return [];
  try {
    const rows = _rows(await db.execute(sql`SELECT org_id, role FROM forge_memberships WHERE user_id = ${userId} AND status = 'active' ORDER BY created_at`));
    const out: Membership[] = rows.map((r) => ({ orgId: String(r.org_id), role: String(r.role) }));
    if (POLICY.table && POLICY.nameColumn && out.length) {
      try {
        const names = _rows(await db.execute(sql.raw(
          `SELECT id::text AS id, "${POLICY.nameColumn}" AS name FROM "${POLICY.table}" WHERE id::text IN (${out.map((m) => `'${m.orgId.replace(/'/g, "''")}'`).join(",")})`)));
        const byId = new Map(names.map((n) => [String(n.id), n.name]));
        for (const m of out) m.orgName = byId.get(m.orgId) ?? null;
      } catch { /* names are a nicety */ }
    }
    return out;
  } catch (err) {
    console.warn("[tenancy] memberships could not be read:", err);
    return [];
  }
}

/** Every organisation, for a platform role that may switch into any. */
export async function allOrganisations(): Promise<Array<{ orgId: string; orgName: string | null }>> {
  await policy();
  if (!tenancyOn() || !POLICY.table) return [];
  try {
    const rows = _rows(await db.execute(sql.raw(
      `SELECT id::text AS id${POLICY.nameColumn ? `, "${POLICY.nameColumn}" AS name` : ""} FROM "${POLICY.table}" ORDER BY 1 LIMIT 200`)));
    return rows.map((r) => ({ orgId: String(r.id), orgName: r.name ?? null }));
  } catch {
    return [];
  }
}

export function isPlatformRole(role: string | null | undefined): boolean {
  return Boolean(role) && POLICY.platformRoles.includes(String(role));
}

/**
 * What a person is, in the organisation they act in: the active org (the
 * stored one when they still belong to it, else their first), and the
 * effective role — a platform role as it is, else the membership's.
 */
export async function resolve(user: { id: string; role?: string | null; activeOrgId?: string | null }):
  Promise<{ activeOrgId: string | null; role: string | null; orgRole: string | null; memberships: Membership[] }> {
  await policy();
  const base = user.role ? String(user.role) : null;
  if (!tenancyOn()) return { activeOrgId: null, role: base, orgRole: null, memberships: [] };
  const memberships = await membershipsOf(String(user.id));
  const platform = isPlatformRole(base);
  let active: string | null = user.activeOrgId ? String(user.activeOrgId) : null;
  if (!platform && active && !memberships.some((m) => m.orgId === active)) active = null;
  if (!active && memberships.length) active = memberships[0].orgId;
  const membership = memberships.find((m) => m.orgId === active) ?? null;
  return { activeOrgId: active, role: platform ? base : (membership?.role ?? base), orgRole: membership?.role ?? null, memberships };
}

export async function setActive(userId: string, orgId: string): Promise<void> {
  await db.execute(sql`UPDATE users SET active_org_id = ${orgId} WHERE id = ${userId}::uuid`);
}

export async function join(userId: string, orgId: string, role: string, invitedBy?: string | null): Promise<void> {
  await db.execute(sql`
    INSERT INTO forge_memberships (user_id, org_id, role, status, invited_by)
    VALUES (${userId}, ${orgId}, ${role}, 'active', ${invitedBy ?? null})
    ON CONFLICT (user_id, org_id) DO UPDATE SET role = EXCLUDED.role, status = 'active'
  `);
}

/** A new organisation, named, as the tenant entity's row. */
export async function createOrganisation(name: string): Promise<string | null> {
  await policy();
  if (!POLICY.table) return null;
  const col = POLICY.nameColumn ?? "name";
  const rows = _rows(await db.execute(sql.raw(
    `INSERT INTO "${POLICY.table}" ("${col}") VALUES ('${String(name).replace(/'/g, "''")}') RETURNING id::text AS id`)));
  return rows[0]?.id ? String(rows[0].id) : null;
}
