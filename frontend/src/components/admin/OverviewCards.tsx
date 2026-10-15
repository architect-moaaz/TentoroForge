"use client";

import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import type { AdminOverview } from "@/lib/admin-types";

function Stat({ label, value, href, note }: { label: string; value: number | string; href?: string; note?: string }) {
  const body = (
    <Card className={href ? "transition-colors hover:bg-muted/40" : ""}>
      <CardContent className="p-4">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-semibold">{value}</p>
        {note && <p className="text-xs text-muted-foreground">{note}</p>}
      </CardContent>
    </Card>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

export function OverviewCards({ data }: { data: AdminOverview }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      <Stat label="People" value={data.people} href="/admin/people" note={`${data.super_admins} super admin${data.super_admins === 1 ? "" : "s"}`} />
      <Stat label="Disabled logins" value={data.disabled_logins} href="/admin/people" />
      <Stat label="Organisations" value={data.orgs.active} href="/admin/orgs" note="active" />
      <Stat label="Blocked" value={data.orgs.blocked} href="/admin/orgs?status=blocked" note={`${data.orgs.removed} removed`} />
      <Stat label="Apps" value={data.apps} href="/admin/apps" />
      <Stat label="Deployments" value={data.deployments} href="/admin/apps" />
    </div>
  );
}
