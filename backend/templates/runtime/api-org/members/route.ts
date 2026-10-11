/**
 * /api/org/members — the members of the organisation I act in.
 *
 * GET lists them; POST {email, name?, role} invites one (a login with a
 * one-time setup link, as the roster does); PATCH {userId, role} re-roles;
 * DELETE {userId} removes. Only the organisation's admin role, or a platform
 * role, may change members. Forge runtime — do not remove.
 */
import { NextResponse } from "next/server";
import crypto from "node:crypto";
import bcrypt from "bcryptjs";
import { sql } from "drizzle-orm";
import { db } from "@/db";
import { auth } from "@/auth";
import * as tenancy from "@/lib/tenancy";

export const runtime = "nodejs";

function _rows(res: unknown): any[] {
  return Array.isArray(res) ? res : ((res as { rows?: any[] })?.rows ?? []);
}

async function _who(): Promise<{ user: any; orgId: string; admin: boolean } | Response> {
  const user = (await auth())?.user as any;
  if (!user?.id) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  const pol = await tenancy.policy();
  if (!tenancy.tenancyOn()) return NextResponse.json({ error: "This application has one organisation." }, { status: 404 });
  const orgId = String(user.activeOrgId ?? "");
  if (!orgId) return NextResponse.json({ error: "You are in no organisation." }, { status: 409 });
  const admin = tenancy.isPlatformRole(user.role) || (Boolean(pol.adminRole) && String(user.orgRole ?? user.role) === pol.adminRole);
  return { user, orgId, admin };
}

export async function GET(): Promise<Response> {
  const who = await _who();
  if (who instanceof Response) return who;
  const rows = _rows(await db.execute(sql`
    SELECT m.user_id, m.role, m.status, u.email, u.name, u.is_active
    FROM forge_memberships m JOIN users u ON u.id::text = m.user_id
    WHERE m.org_id = ${who.orgId} AND m.status = 'active' ORDER BY m.created_at
  `));
  return NextResponse.json({ orgId: who.orgId, members: rows, canManage: who.admin });
}

export async function POST(req: Request): Promise<Response> {
  const who = await _who();
  if (who instanceof Response) return who;
  if (!who.admin) return NextResponse.json({ error: "Only the organisation's administrator invites people." }, { status: 403 });
  const pol = await tenancy.policy();
  const body = await req.json().catch(() => ({}));
  const email = String(body?.email ?? "").trim().toLowerCase();
  const role = String(body?.role ?? pol.memberRoles[0] ?? "member");
  if (!email.includes("@")) return NextResponse.json({ error: "An email address is what identifies a login." }, { status: 400 });
  if (pol.memberRoles.length && !pol.memberRoles.includes(role)) {
    return NextResponse.json({ error: `A member is one of: ${pol.memberRoles.join(", ")}.` }, { status: 400 });
  }
  // The person: an existing login joins now; a new one gets a login with no
  // password and a one-time setup link, exactly as the roster's invites do.
  const existing = _rows(await db.execute(sql`SELECT id::text AS id FROM users WHERE email = ${email} LIMIT 1`))[0];
  if (existing?.id) {
    await tenancy.join(String(existing.id), who.orgId, role, String(who.user.id));
    return NextResponse.json({ ok: true, joined: true, userId: existing.id });
  }
  const token = crypto.randomBytes(24).toString("base64url");
  const tokenHash = crypto.createHash("sha256").update(token).digest("hex");
  const issue = crypto.randomUUID();
  const expires = new Date(Date.now() + 7 * 86_400_000);
  const password = await bcrypt.hash(crypto.randomUUID(), 12);
  const created = _rows(await db.execute(sql`
    INSERT INTO users (email, password, name, is_active, active_org_id) VALUES (${email}, ${password}, ${String(body?.name ?? email)}, false, ${who.orgId})
    ON CONFLICT (email) DO NOTHING RETURNING id::text AS id
  `))[0];
  if (!created?.id) return NextResponse.json({ error: "That login could not be made." }, { status: 500 });
  await tenancy.join(String(created.id), who.orgId, role, String(who.user.id));
  await db.execute(sql`
    INSERT INTO forge_invites (email, token_hash, issue, purpose, expires_at, org_id, role)
    VALUES (${email}, ${tokenHash}, ${issue}, 'invite', ${expires.toISOString()}::timestamp, ${who.orgId}, ${role})
    ON CONFLICT (email) DO UPDATE SET token_hash = EXCLUDED.token_hash, issue = EXCLUDED.issue, expires_at = EXCLUDED.expires_at,
      used_at = NULL, org_id = EXCLUDED.org_id, role = EXCLUDED.role
  `);
  return NextResponse.json({ ok: true, invited: true, userId: created.id, setupPath: `/set-password?token=${token}` }, { status: 201 });
}

export async function PATCH(req: Request): Promise<Response> {
  const who = await _who();
  if (who instanceof Response) return who;
  if (!who.admin) return NextResponse.json({ error: "Only the organisation's administrator changes roles." }, { status: 403 });
  const pol = await tenancy.policy();
  const body = await req.json().catch(() => ({}));
  const userId = String(body?.userId ?? ""); const role = String(body?.role ?? "");
  if (!userId || !role) return NextResponse.json({ error: "Which member, and which role?" }, { status: 400 });
  if (pol.memberRoles.length && !pol.memberRoles.includes(role)) {
    return NextResponse.json({ error: `A member is one of: ${pol.memberRoles.join(", ")}.` }, { status: 400 });
  }
  await db.execute(sql`UPDATE forge_memberships SET role = ${role} WHERE user_id = ${userId} AND org_id = ${who.orgId}`);
  return NextResponse.json({ ok: true });
}

export async function DELETE(req: Request): Promise<Response> {
  const who = await _who();
  if (who instanceof Response) return who;
  if (!who.admin) return NextResponse.json({ error: "Only the organisation's administrator removes people." }, { status: 403 });
  const body = await req.json().catch(() => ({}));
  const userId = String(body?.userId ?? "");
  if (!userId) return NextResponse.json({ error: "Which member?" }, { status: 400 });
  if (userId === String(who.user.id)) return NextResponse.json({ error: "You cannot remove yourself." }, { status: 409 });
  await db.execute(sql`UPDATE forge_memberships SET status = 'removed' WHERE user_id = ${userId} AND org_id = ${who.orgId}`);
  await db.execute(sql`UPDATE users SET active_org_id = NULL WHERE id::text = ${userId} AND active_org_id = ${who.orgId}`);
  return NextResponse.json({ ok: true });
}
