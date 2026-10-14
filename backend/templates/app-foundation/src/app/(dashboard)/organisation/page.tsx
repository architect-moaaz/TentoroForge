/**
 * The organisation I act in: its members, their roles; invite, re-role,
 * remove when I administer it. Rendered for every application with several
 * organisations; one with none says so. Forge runtime — do not edit by hand.
 */
import { cookies, headers } from "next/headers";
import { MembersPanel } from "./MembersPanel";
import { AddressPanel } from "./AddressPanel";

export const dynamic = "force-dynamic";

async function read(path: string): Promise<any> {
  const cookieHeader = (await cookies()).getAll().map((c) => `${c.name}=${c.value}`).join("; ");
  const host = (await headers()).get("host") || "localhost:3000";
  const proto = (await headers()).get("x-forwarded-proto") || "http";
  try {
    const res = await fetch(`${proto}://${host}${path}`, { headers: { cookie: cookieHeader }, cache: "no-store" });
    return { status: res.status, body: await res.json().catch(() => ({})) };
  } catch (err) {
    return { status: 0, body: { error: String(err) } };
  }
}

export default async function OrganisationPage() {
  const org = await read("/api/org");
  const members = await read("/api/org/members");
  const address = await read("/api/org/address");
  if (org.status === 404 || !org.body?.organisations?.length) {
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <h1 className="text-2xl font-semibold mb-1">Organisation</h1>
        <p className="text-muted-foreground">{org.body?.error ?? "You are in no organisation yet."}</p>
      </div>
    );
  }
  const active = org.body.organisations.find((o: any) => o.orgId === org.body.activeOrgId) ?? org.body.organisations[0];
  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-semibold mb-1">{active?.orgName ?? "Organisation"}</h1>
      <p className="text-sm text-muted-foreground mb-6">Who belongs here, and what they may do.</p>
      {address.status === 200 && address.body?.slug && (
        <AddressPanel slug={String(address.body.slug)} domain={String(address.body.domain)} canManage={Boolean(address.body.canManage)} />
      )}
      <MembersPanel members={members.body?.members ?? []} canManage={Boolean(members.body?.canManage)} me={String((org.body as any).me ?? "")} />
    </div>
  );
}
