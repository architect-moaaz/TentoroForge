"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { adminApi, adminKeys } from "@/lib/admin-api";
import { OverviewCards } from "@/components/admin/OverviewCards";
import { AuditTable } from "@/components/admin/AuditTable";

export default function AdminOverviewPage() {
  const overview = useQuery({ queryKey: adminKeys.overview, queryFn: adminApi.overview });
  const recent = useQuery({ queryKey: adminKeys.audit({}, 1), queryFn: () => adminApi.audit({}, 1, 15) });
  return (
    <div className="mx-auto max-w-6xl space-y-8 p-6">
      <div>
        <p className="mb-1 text-xs font-medium uppercase tracking-widest text-primary">Cockpit</p>
        <h1 className="text-2xl font-bold tracking-tight">The platform at a glance</h1>
      </div>
      {overview.data ? <OverviewCards data={overview.data} /> : <p className="text-sm text-muted-foreground">Loading…</p>}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-base font-semibold">Latest activity</h2>
          <Link href="/admin/activity" className="text-xs text-primary hover:underline">everything →</Link>
        </div>
        <div className="rounded-lg border bg-white dark:bg-slate-900">
          <AuditTable rows={recent.data ?? []} />
        </div>
      </section>
    </div>
  );
}
