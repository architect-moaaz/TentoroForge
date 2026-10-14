"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { adminApi, adminKeys } from "@/lib/admin-api";
import { AuditTable } from "@/components/admin/AuditTable";

export default function AdminActivityPage() {
  const [action, setAction] = useState("");
  const [orgId, setOrgId] = useState("");
  const [since, setSince] = useState("");
  const [page, setPage] = useState(1);
  const filters: Record<string, string> = {};
  if (action) filters.action = action;
  if (orgId) filters.org_id = orgId;
  if (since) filters.since = `${since}T00:00:00Z`;
  const rows = useQuery({ queryKey: adminKeys.audit(filters, page), queryFn: () => adminApi.audit(filters, page) });
  const people = useQuery({ queryKey: adminKeys.people("", 1), queryFn: () => adminApi.people("", 1) });
  const names = Object.fromEntries((people.data?.items ?? []).map((p) => [p.id, p.email]));
  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <h1 className="text-2xl font-bold tracking-tight">Activity</h1>
      <p className="text-sm text-muted-foreground">Everything done from the cockpit, every bootstrap, and every request made while impersonating someone.</p>
      <div className="flex flex-wrap items-center gap-2">
        <Input className="w-48" placeholder="Action (org., person., app.…)" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} />
        <Input className="w-72" placeholder="Organisation id" value={orgId} onChange={(e) => { setOrgId(e.target.value); setPage(1); }} />
        <Input className="w-40" type="date" value={since} onChange={(e) => { setSince(e.target.value); setPage(1); }} />
      </div>
      <div className="rounded-lg border bg-white dark:bg-slate-900">
        <AuditTable rows={rows.data ?? []} names={names} />
      </div>
      <div className="flex items-center justify-end gap-2 text-xs">
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
        <span>page {page}</span>
        <Button size="sm" variant="outline" disabled={(rows.data?.length ?? 0) < 50} onClick={() => setPage(page + 1)}>Next</Button>
      </div>
    </div>
  );
}
