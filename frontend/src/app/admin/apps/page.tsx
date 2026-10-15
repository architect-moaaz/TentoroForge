"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ApiError } from "@/lib/api";
import { adminApi, adminKeys } from "@/lib/admin-api";
import type { AdminApp, TeardownReport } from "@/lib/admin-types";
import { AppsTable } from "@/components/admin/AppsTable";
import { TypedConfirmDialog } from "@/components/admin/TypedConfirmDialog";
import { TeardownResult } from "@/app/admin/orgs/[orgId]/page";
import { useAuthStore } from "@/stores/auth";

export default function AdminAppsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const impersonate = useAuthStore((s) => s.impersonate);
  const [q, setQ] = useState("");
  const [org, setOrg] = useState("all");
  const [page, setPage] = useState(1);
  const [deleting, setDeleting] = useState<AdminApp | null>(null);
  const [report, setReport] = useState<TeardownReport | null>(null);
  const orgFilter = org === "all" ? "" : org;
  const apps = useQuery({ queryKey: adminKeys.apps(q, orgFilter, page), queryFn: () => adminApi.apps(q, orgFilter, page) });
  const orgs = useQuery({ queryKey: adminKeys.orgs("", "", 1), queryFn: () => adminApi.orgs("", "", 1) });

  const refresh = () => { qc.invalidateQueries({ queryKey: ["admin", "apps"] }); qc.invalidateQueries({ queryKey: ["admin", "audit"] }); };
  const fail = (e: unknown, what: string) => toast.error(e instanceof ApiError ? e.message : what);
  const action = (fn: (id: string) => Promise<unknown>, done: string) =>
    useMutation({ mutationFn: fn, onSuccess: () => { toast.success(done); refresh(); }, onError: (e) => fail(e, "That did not go through") });
  const stopBuild = action(adminApi.stopBuild, "Stop requested");
  const stopPreview = action(adminApi.stopPreview, "Preview stopped");
  const archive = action(adminApi.archive, "Archived");
  const unarchive = action(adminApi.unarchive, "Unarchived");
  const deleteApp = useMutation({
    mutationFn: (a: AdminApp) => adminApi.deleteApp(a.id, a.short_id),
    onSuccess: (r) => { setDeleting(null); setReport(r); refresh(); }, onError: (e) => fail(e, "Not deleted"),
  });

  async function openAsOwner(a: AdminApp) {
    if (!a.org || !a.owner_email) return;
    const members = await adminApi.members(a.org.id);
    const owner = members.find((m) => m.email === a.owner_email && m.user_id);
    if (!owner?.user_id) { toast.error("The owner is not a member any more"); return; }
    try {
      const defaultOrg = await impersonate(owner.user_id);
      qc.clear();
      router.push(`/org/${defaultOrg || a.org.id}/projects/${a.id}`);
    } catch (e) {
      fail(e, "Could not impersonate the owner");
    }
  }

  const total = apps.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / (apps.data?.page_size ?? 50)));
  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <h1 className="text-2xl font-bold tracking-tight">Apps</h1>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-72">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-8" placeholder="Name or id" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        </div>
        <Select value={org} onValueChange={(v) => { setOrg(v); setPage(1); }}>
          <SelectTrigger className="w-56"><SelectValue placeholder="Every organisation" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Every organisation</SelectItem>
            {(orgs.data?.items ?? []).map((o) => <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">{total} app{total === 1 ? "" : "s"}</span>
      </div>
      <div className="rounded-lg border bg-white dark:bg-slate-900">
        <AppsTable rows={apps.data?.items ?? []} onStopBuild={(a) => stopBuild.mutate(a.id)} onStopPreview={(a) => stopPreview.mutate(a.id)}
                   onArchive={(a) => archive.mutate(a.id)} onUnarchive={(a) => unarchive.mutate(a.id)} onDelete={setDeleting} onOpenAsOwner={openAsOwner} />
      </div>
      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-xs">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <span>{page} / {pages}</span>
          <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
      <TypedConfirmDialog open={!!deleting} onOpenChange={(v) => !v && setDeleting(null)} title={`Delete ${deleting?.name}`}
                          prompt="Its preview, its database on the apps server, its Neon projects, its folder and its rows go. A published Vercel deployment stays until removed by hand."
                          expected={deleting?.short_id || ""} confirmText="Delete" pending={deleteApp.isPending} onConfirm={() => deleting && deleteApp.mutate(deleting)} />
      <TeardownResult report={report} onClose={() => setReport(null)} />
    </div>
  );
}
