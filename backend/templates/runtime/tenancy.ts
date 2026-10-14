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
  const id = rows[0]?.id ? String(rows[0].id) : null;
  if (id && orgDomain()) await ensureSlugs().catch(() => {});
  return id;
}

// ── An address per organisation ─────────────────────────────────────────
//
// When the platform attached a wildcard (`*.clinicapp.com`) to the app it
// sets FORGE_ORG_DOMAIN, and each organisation answers at
// `<slug>.clinicapp.com`: the host decides the organisation a request acts
// in (`atAddress`, read by `auth()`). The slugs are the runtime's own table
// (`forge_org_addresses`), given from the organisation's name the first time
// they are needed and changed by its admin. Without the variable, nothing
// here does anything.

/** Never an organisation's address: the app's own names, and the platform's. */
export const RESERVED_SLUGS = new Set(["www", "app", "api", "admin", "login", "signin", "signup", "auth", "mail",
  "email", "smtp", "static", "assets", "cdn", "status", "help", "support", "docs", "blog", "dev", "staging", "test",
  "preview", "billing", "security", "root", "system", "_next"]);

/** A request acts in no organisation: matches no row, and a write is refused. */
export const NO_ORG = "00000000-0000-0000-0000-000000000000";

/** The domain organisations' addresses sit under, or "". */
export function orgDomain(): string {
  return String(process.env.FORGE_ORG_DOMAIN || "").trim().toLowerCase().replace(/^\*\./, "").replace(/\.$/, "");
}

export function slugify(name: string): string {
  return String(name || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40).replace(/-+$/g, "");
}

/** `acme.clinicapp.com` → `acme`; another host, a nested one or a reserved name → null. */
export function slugFromHost(host: string | null | undefined): string | null {
  const base = orgDomain();
  if (!base || !host) return null;
  const h = String(host).toLowerCase().split(",")[0].trim().replace(/:\d+$/, "");
  if (!h.endsWith(`.${base}`)) return null;
  const label = h.slice(0, -base.length - 1);
  if (!label || label.includes(".") || RESERVED_SLUGS.has(label)) return null;
  return label;
}

export function addressOf(slug: string): string {
  return `https://${slug}.${orgDomain()}`;
}

function _q(v: string): string {
  return `'${String(v).replace(/'/g, "''")}'`;
}

/** Every organisation without an address gets one, from its name. */
export async function ensureSlugs(): Promise<void> {
  await policy();
  if (!tenancyOn() || !POLICY.table) return;
  const nameSel = POLICY.nameColumn ? `t."${POLICY.nameColumn}"` : "NULL";
  const missing = _rows(await db.execute(sql.raw(
    `SELECT t.id::text AS id, ${nameSel} AS name FROM "${POLICY.table}" t
     LEFT JOIN forge_org_addresses a ON a.org_id = t.id::text WHERE a.org_id IS NULL LIMIT 500`)));
  for (const row of missing) {
    let base = slugify(String(row.name ?? "")) || "org";
    if (base.length < 3 || RESERVED_SLUGS.has(base)) base = `${base}-org`;
    for (let i = 1; i <= 50; i++) {
      const slug = i === 1 ? base : `${base}-${i}`;
      const made = _rows(await db.execute(sql.raw(
        `INSERT INTO forge_org_addresses (org_id, slug) VALUES (${_q(row.id)}, ${_q(slug)}) ON CONFLICT DO NOTHING RETURNING slug`)));
      if (made.length) break;
      const has = _rows(await db.execute(sql.raw(`SELECT 1 FROM forge_org_addresses WHERE org_id = ${_q(row.id)}`)));
      if (has.length) break;
    }
  }
}

export async function slugOf(orgId: string): Promise<string | null> {
  const read = async () => _rows(await db.execute(sql.raw(`SELECT slug FROM forge_org_addresses WHERE org_id = ${_q(orgId)}`)))[0]?.slug;
  let slug = await read();
  if (!slug) { await ensureSlugs(); slug = await read(); }
  return slug ? String(slug) : null;
}

export async function orgBySlug(slug: string): Promise<string | null> {
  const read = async () => _rows(await db.execute(sql.raw(`SELECT org_id FROM forge_org_addresses WHERE slug = ${_q(slug)}`)))[0]?.org_id;
  let orgId = await read();
  if (!orgId) { await ensureSlugs(); orgId = await read(); }
  return orgId ? String(orgId) : null;
}

/** An organisation's admin renames its address. The old one stops answering. */
export async function setSlug(orgId: string, raw: string): Promise<{ ok: true; slug: string } | { ok: false; error: string }> {
  const slug = slugify(raw);
  if (slug.length < 3) return { ok: false, error: "The address needs at least 3 letters or digits." };
  if (RESERVED_SLUGS.has(slug)) return { ok: false, error: `${slug} is kept for the application; choose another.` };
  const taken = _rows(await db.execute(sql.raw(`SELECT org_id FROM forge_org_addresses WHERE slug = ${_q(slug)}`)))[0];
  if (taken && String(taken.org_id) !== String(orgId)) return { ok: false, error: `${slug} is another organisation's address.` };
  await db.execute(sql.raw(`INSERT INTO forge_org_addresses (org_id, slug) VALUES (${_q(orgId)}, ${_q(slug)})
    ON CONFLICT (org_id) DO UPDATE SET slug = EXCLUDED.slug, updated_at = now()`));
  return { ok: true, slug };
}

/**
 * The organisation a request acts in, decided by the address it was opened
 * at: a member acts there in their role in it (a platform role anywhere); a
 * person who does not belong acts in none and is told (`outsideOrg`). Null
 * when the address names no organisation.
 */
export async function atAddress(user: { id: string; role?: string | null; activeOrgId?: string | null },
                                host: string | null | undefined):
  Promise<null | { activeOrgId: string; role: string | null; orgRole: string | null; outsideOrg?: string }> {
  await policy();
  if (!tenancyOn()) return null;
  const slug = slugFromHost(host);
  if (!slug) return null;
  const outside = { activeOrgId: NO_ORG, role: user.role ? String(user.role) : null, orgRole: null, outsideOrg: slug };
  const orgId = await orgBySlug(slug);
  if (!orgId) return outside;
  const inOrg = await resolve({ id: String(user.id), role: user.role ?? null, activeOrgId: orgId });
  if (inOrg.activeOrgId !== orgId) return outside;
  if (String(user.activeOrgId ?? "") !== orgId) {
    // Where they went last is where they land next time without an address.
    setActive(String(user.id), orgId).catch(() => {});
  }
  return { activeOrgId: orgId, role: inOrg.role, orgRole: inOrg.orgRole };
}
