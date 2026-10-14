/**
 * /api/org — the organisation a person acts in, its members, and switching.
 *
 * GET: my memberships (and every organisation for a platform role) and the
 * active one. POST {orgId}: switch — only into an organisation I belong to,
 * or any for a platform role. Forge runtime — do not remove.
 */
import { NextResponse } from "next/server";
import { auth } from "@/auth";
import * as tenancy from "@/lib/tenancy";

export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  const user = (await auth())?.user as any;
  if (!user?.id) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  await tenancy.policy();
  if (!tenancy.tenancyOn()) return NextResponse.json({ organisations: [], activeOrgId: null, platform: false });
  const mine = await tenancy.membershipsOf(String(user.id));
  const platform = tenancy.isPlatformRole(user.role);
  const organisations: Array<Record<string, unknown>> = platform ? await tenancy.allOrganisations()
    : mine.map((m) => ({ orgId: m.orgId, orgName: m.orgName ?? null, role: m.role }));
  // WITH AN ADDRESS EACH, switching is going there.
  if (tenancy.orgDomain()) {
    for (const o of organisations) {
      try {
        const slug = await tenancy.slugOf(String(o.orgId));
        if (slug) o.address = tenancy.addressOf(slug);
      } catch { /* no address table yet: switching stays in place */ }
    }
  }
  return NextResponse.json({ organisations, activeOrgId: user.activeOrgId ?? null, platform, role: user.role ?? null });
}

export async function POST(req: Request): Promise<Response> {
  const user = (await auth())?.user as any;
  if (!user?.id) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  await tenancy.policy();
  if (!tenancy.tenancyOn()) return NextResponse.json({ error: "This application has one organisation." }, { status: 404 });
  const body = await req.json().catch(() => ({}));
  const orgId = String(body?.orgId ?? "");
  if (!orgId) return NextResponse.json({ error: "Which organisation?" }, { status: 400 });
  const mine = await tenancy.membershipsOf(String(user.id));
  if (!tenancy.isPlatformRole(user.role) && !mine.some((m) => m.orgId === orgId)) {
    return NextResponse.json({ error: "You do not belong to that organisation." }, { status: 403 });
  }
  await tenancy.setActive(String(user.id), orgId);
  return NextResponse.json({ ok: true, activeOrgId: orgId });
}
