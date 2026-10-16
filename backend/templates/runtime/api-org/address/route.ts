/**
 * /api/org/address — the address the organisation I act in answers at.
 *
 * GET: its slug and full address, the domain they sit under, and whether I
 * may change it. PUT {slug}: rename it — only the organisation's admin role
 * or a platform role. 404 when organisations have no addresses here.
 * Forge runtime — do not remove.
 */
import { NextResponse } from "next/server";
import { auth } from "@/auth";
import * as tenancy from "@/lib/tenancy";

export const runtime = "nodejs";

async function _who(): Promise<{ orgId: string; admin: boolean } | Response> {
  const user = (await auth())?.user as any;
  if (!user?.id) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  const pol = await tenancy.policy();
  if (!tenancy.tenancyOn() || !tenancy.orgDomain()) {
    return NextResponse.json({ error: "Organisations have no addresses of their own here." }, { status: 404 });
  }
  const orgId = String(user.activeOrgId ?? "");
  if (!orgId || orgId === tenancy.NO_ORG) return NextResponse.json({ error: "You are in no organisation." }, { status: 409 });
  const admin = tenancy.isPlatformRole(user.role) || (Boolean(pol.adminRole) && String(user.orgRole ?? user.role) === pol.adminRole);
  return { orgId, admin };
}

export async function GET(): Promise<Response> {
  const who = await _who();
  if (who instanceof Response) return who;
  const slug = await tenancy.slugOf(who.orgId);
  return NextResponse.json({ slug, address: slug ? tenancy.addressOf(slug) : null, domain: tenancy.orgDomain(),
                             canManage: who.admin });
}

export async function PUT(req: Request): Promise<Response> {
  const who = await _who();
  if (who instanceof Response) return who;
  if (!who.admin) return NextResponse.json({ error: "Only the organisation's admin may change its address." }, { status: 403 });
  const body = await req.json().catch(() => ({}));
  const out = await tenancy.setSlug(who.orgId, String(body?.slug ?? ""));
  if (!out.ok) return NextResponse.json({ error: out.error }, { status: 400 });
  return NextResponse.json({ slug: out.slug, address: tenancy.addressOf(out.slug), domain: tenancy.orgDomain(), canManage: true });
}
