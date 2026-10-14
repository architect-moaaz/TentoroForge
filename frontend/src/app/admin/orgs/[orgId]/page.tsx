"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ApiError } from "@/lib/api";
import { adminApi, adminKeys } from "@/lib/admin-api";
import type { AdminApp, AdminMember, TeardownReport } from "@/lib/admin-types";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { ReasonDialog } from "@/components/admin/ReasonDialog";
import { TypedConfirmDialog } from "@/components/admin/TypedConfirmDialog";
import { AddMemberDialog } from "@/components/admin/AddMemberDialog";
import { AppsTable } from "@/components/admin/AppsTable";
import { CreditEntryDialog } from "@/components/admin/CreditEntryDialog";
import { LimitsEditor } from "@/components/admin/LimitsEditor";
import { when } from "@/components/admin/PeopleTable";
import { SpendPanel } from "@/components/usage/SpendPanel";
import { useAuthStore } from "@/stores/auth";

function said(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function TeardownResult({ report, onClose }: { report: TeardownReport | null; onClose: () => void }) {
  return (
    <Dialog open={!!report} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>What was removed</DialogTitle></DialogHeader>
        <ul className="max-h-64 space-y-1 overflow-auto text-sm">
          {report?.removed.map((s, i) => <li key={`r${i}`}>✓ {s.step}: <code className="text-xs">{s.target}</code></li>)}
          {report?.failed.map((s, i) => <li key={`f${i}`} className="text-destructive">✗ {s.step}: <code className="text-xs">{s.target}</code> — {s.error}</li>)}
        </ul>
        {report && report.failed.length === 0 && <p className="text-xs text-muted-foreground">Everything is gone.</p>}
      </DialogContent>
    </Dialog>
  );
}

export default function AdminOrgPage({ params }: { params: Promise<{ orgId: string }> }) {
  const { orgId } = use(params);
  const router = useRouter();
  const qc = useQueryClient();
  const impersonate = useAuthStore((s) => s.impersonate);
  const org = useQuery({ queryKey: adminKeys.org(orgId), queryFn: () => adminApi.org(orgId) });
  const members = useQuery({ queryKey: adminKeys.members(orgId), queryFn: () => adminApi.members(orgId) });
  const apps = useQuery({ queryKey: adminKeys.apps("", orgId, 1), queryFn: () => adminApi.apps("", orgId, 1) });
  const credits = useQuery({ queryKey: adminKeys.creditEntries(orgId), queryFn: () => adminApi.creditEntries(orgId) });

  const [dialog, setDialog] = useState<"block" | "remove" | "purge" | "add" | "entry" | null>(null);
  const [deleting, setDeleting] = useState<AdminApp | null>(null);
  const [report, setReport] = useState<TeardownReport | null>(null);
  const [purged, setPurged] = useState(false);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: adminKeys.org(orgId) });
    qc.invalidateQueries({ queryKey: ["admin", "orgs"] });
    qc.invalidateQueries({ queryKey: adminKeys.members(orgId) });
    qc.invalidateQueries({ queryKey: ["admin", "apps"] });
    qc.invalidateQueries({ queryKey: ["admin", "credits"] });
    qc.invalidateQueries({ queryKey: ["admin", "audit"] });
  };
  const simple = <T,>(fn: () => Promise<T>, done: string) =>
    useMutation({ mutationFn: fn, onSuccess: () => { toast.success(done); refresh(); setDialog(null); },
                  onError: (e) => toast.error(said(e, "That did not go through")) });

  const block = useMutation({
    mutationFn: (reason: string) => adminApi.block(orgId, reason),
    onSuccess: () => { toast.success("Blocked"); refresh(); setDialog(null); }, onError: (e) => toast.error(said(e, "Not blocked")),
  });
  const remove = useMutation({
    mutationFn: (reason: string) => adminApi.remove(orgId, reason),
    onSuccess: () => { toast.success("Removed"); refresh(); setDialog(null); }, onError: (e) => toast.error(said(e, "Not removed")),
  });
  const reinstate = simple(() => adminApi.reinstate(orgId), "Reinstated");
  const purge = useMutation({
    mutationFn: () => adminApi.purge(orgId, org.data?.slug || ""),
    onSuccess: (r) => { setDialog(null); setPurged(true); setReport(r); qc.invalidateQueries({ queryKey: ["admin"] }); },
    onError: (e) => toast.error(said(e, "Not purged")),
  });
  const addMember = useMutation({
    mutationFn: ({ email, role }: { email: string; role: string }) => adminApi.addMember(orgId, email, role),
    onSuccess: (m) => { toast.success(m.invite_status === "accepted" ? "Added" : "Invited"); refresh(); setDialog(null); },
    onError: (e) => toast.error(said(e, "Not added")),
  });
  const setRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) => adminApi.setRole(orgId, userId, role),
    onSuccess: () => { toast.success("Role changed"); refresh(); }, onError: (e) => toast.error(said(e, "Role unchanged")),
  });
  const removeMember = useMutation({
    mutationFn: (userId: string) => adminApi.removeMember(orgId, userId),
    onSuccess: () => { toast.success("Removed from the organisation"); refresh(); }, onError: (e) => toast.error(said(e, "Not removed")),
  });
  const transfer = useMutation({
    mutationFn: (userId: string) => adminApi.transferOwnership(orgId, userId),
    onSuccess: () => { toast.success("Ownership transferred"); refresh(); }, onError: (e) => toast.error(said(e, "Not transferred")),
  });
  const cancelInvite = useMutation({
    mutationFn: (inviteId: string) => adminApi.cancelInvite(orgId, inviteId),
    onSuccess: () => { toast.success("Invite cancelled"); refresh(); }, onError: (e) => toast.error(said(e, "Not cancelled")),
  });
  const resendInvite = useMutation({
    mutationFn: (inviteId: string) => adminApi.resendInvite(orgId, inviteId),
    onSuccess: (r) => toast.success(r.emailed ? "Invite sent again" : `Accept link: ${r.accept_path}`),
    onError: (e) => toast.error(said(e, "Not sent")),
  });
  const appAction = (fn: (id: string) => Promise<unknown>, done: string) => useMutation({
    mutationFn: fn, onSuccess: () => { toast.success(done); refresh(); }, onError: (e) => toast.error(said(e, "That did not go through")),
  });
  const stopBuild = appAction(adminApi.stopBuild, "Stop requested");
  const stopPreview = appAction(adminApi.stopPreview, "Preview stopped");
  const archive = appAction(adminApi.archive, "Archived");
  const unarchive = appAction(adminApi.unarchive, "Unarchived");
  const deleteApp = useMutation({
    mutationFn: (a: AdminApp) => adminApi.deleteApp(a.id, a.short_id),
    onSuccess: (r) => { setDeleting(null); setReport(r); refresh(); }, onError: (e) => toast.error(said(e, "Not deleted")),
  });
  const addEntry = useMutation({
    mutationFn: (body: { amount_usd: number; kind: "opening" | "top_up" | "adjustment" | "refund"; note: string }) => adminApi.addEntry(orgId, body),
    onSuccess: () => { toast.success("Entry recorded"); refresh(); setDialog(null); }, onError: (e) => toast.error(said(e, "Not recorded")),
  });
  const setLimits = useMutation({
    mutationFn: (limits: Parameters<typeof adminApi.setLimits>[2]) => adminApi.setLimits("org", orgId, limits),
    onSuccess: () => { toast.success("Limits saved"); refresh(); }, onError: (e) => toast.error(said(e, "Limits not saved")),
  });

  async function openAsOwner(a: AdminApp) {
    const owner = members.data?.find((m) => m.email === a.owner_email && m.user_id);
    if (!owner?.user_id) { toast.error("The owner is not a member any more"); return; }
    const defaultOrg = await impersonate(owner.user_id);
    qc.clear();
    router.push(`/org/${defaultOrg || orgId}/projects/${a.id}`);
  }

  const o = org.data;
  const accepted = (members.data ?? []).filter((m) => m.invite_status === "accepted");
  const pending = (members.data ?? []).filter((m) => m.invite_status === "pending");
  const owners = accepted.filter((m) => m.role === "owner").length;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <Link href="/admin/orgs" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ChevronLeft className="h-3 w-3" /> Organisations</Link>
      {o && (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">{o.name} <StatusBadge kind="org" status={o.status} /></h1>
            <p className="text-xs text-muted-foreground">/{o.slug} · owner {o.owner_email || "—"} · created {when(o.created_at)}</p>
            {o.status_reason && <p className="mt-1 text-sm">{o.status === "active" ? "" : `${o.status} — `}{o.status_reason}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            {o.status === "active" && <Button variant="outline" onClick={() => setDialog("block")}>Block…</Button>}
            {o.status !== "removed" && <Button variant="outline" onClick={() => setDialog("remove")}>Remove…</Button>}
            {o.status !== "active" && <Button onClick={() => { if (window.confirm(`Reinstate ${o.name}?`)) reinstate.mutate(); }}>Reinstate</Button>}
            {o.status === "removed" && <Button variant="destructive" onClick={() => setDialog("purge")}>Purge…</Button>}
          </div>
        </div>
      )}

      <Tabs defaultValue="members">
        <TabsList>
          <TabsTrigger value="members">Members ({accepted.length}{pending.length ? ` + ${pending.length} invited` : ""})</TabsTrigger>
          <TabsTrigger value="apps">Apps ({apps.data?.total ?? 0})</TabsTrigger>
          <TabsTrigger value="credits">Credits</TabsTrigger>
        </TabsList>

        <TabsContent value="members" className="space-y-3">
          <div className="flex justify-end"><Button size="sm" onClick={() => setDialog("add")}>Add a person</Button></div>
          <div className="rounded-lg border bg-white dark:bg-slate-900">
            <Table>
              <TableHeader><TableRow><TableHead>Person</TableHead><TableHead>Role</TableHead><TableHead>Joined</TableHead><TableHead /></TableRow></TableHeader>
              <TableBody>
                {(members.data ?? []).map((m: AdminMember) => (
                  <TableRow key={m.id}>
                    <TableCell>
                      <div className="font-medium">{m.name || m.email}</div>
                      <div className="text-xs text-muted-foreground">{m.email}{m.disabled ? " · login disabled" : ""}</div>
                    </TableCell>
                    <TableCell>
                      {m.invite_status === "accepted" && m.user_id ? (
                        <Select value={m.role} onValueChange={(role) => setRole.mutate({ userId: m.user_id!, role })}>
                          <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="owner">owner</SelectItem>
                            <SelectItem value="admin">admin</SelectItem>
                            <SelectItem value="member">member</SelectItem>
                          </SelectContent>
                        </Select>
                      ) : <StatusBadge kind="member" invite_status={m.invite_status} role={m.role} />}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{when(m.joined_at)}</TableCell>
                    <TableCell className="space-x-2 text-right text-xs">
                      {m.invite_status === "accepted" && m.user_id ? (
                        <>
                          {m.role !== "owner" && <button className="text-primary hover:underline" onClick={() => { if (window.confirm(`Make ${m.email} the owner? Other owners become admins.`)) transfer.mutate(m.user_id!); }}>Make owner</button>}
                          <button className="text-destructive hover:underline" disabled={m.role === "owner" && owners === 1}
                                  onClick={() => { if (window.confirm(`Remove ${m.email} from ${o?.name}?`)) removeMember.mutate(m.user_id!); }}>Remove</button>
                        </>
                      ) : (
                        <>
                          <button className="text-primary hover:underline" onClick={() => resendInvite.mutate(m.id)}>Resend</button>
                          <button className="text-destructive hover:underline" onClick={() => cancelInvite.mutate(m.id)}>Cancel</button>
                        </>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        <TabsContent value="apps">
          <div className="rounded-lg border bg-white dark:bg-slate-900">
            <AppsTable rows={apps.data?.items ?? []} onStopBuild={(a) => stopBuild.mutate(a.id)} onStopPreview={(a) => stopPreview.mutate(a.id)}
                       onArchive={(a) => archive.mutate(a.id)} onUnarchive={(a) => unarchive.mutate(a.id)} onDelete={setDeleting} onOpenAsOwner={openAsOwner} />
          </div>
        </TabsContent>

        <TabsContent value="credits" className="space-y-4">
          {o && <SpendPanel scope={{ org: orgId, label: `organisation ${o.name}` }} heading="This organisation's spend" />}
          {credits.data && (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-lg border p-3">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Balance</p>
                {credits.data.balance.known
                  ? <p className={`text-2xl font-semibold ${(credits.data.balance.balance_usd ?? 0) <= 0 ? "text-destructive" : ""}`}>${(credits.data.balance.balance_usd ?? 0).toFixed(2)}</p>
                  : <p className="text-sm text-muted-foreground">unknown — no credit recorded (limits only)</p>}
                <p className="text-xs text-muted-foreground">credit ${credits.data.balance.credit_usd.toFixed(2)} · spent ${credits.data.balance.spent_usd.toFixed(2)} since {credits.data.balance.since ? when(credits.data.balance.since) : "—"} · a build is expected to cost about ${credits.data.build_estimate_usd.toFixed(2)}</p>
                <div className="mt-2"><Button size="sm" onClick={() => setDialog("entry")}>Add entry</Button></div>
              </div>
              <LimitsEditor title="This organisation's limits" initial={Object.fromEntries((credits.data.limits || []).filter((l) => l.scope.startsWith("org:") && l.limit_usd != null).map((l) => [l.period, l.limit_usd!]))}
                            pending={setLimits.isPending} onSave={(l) => setLimits.mutate(l)} />
            </div>
          )}
          <div className="rounded-lg border bg-white dark:bg-slate-900">
            <Table>
              <TableHeader><TableRow><TableHead>When</TableHead><TableHead>Kind</TableHead><TableHead className="text-right">Amount</TableHead><TableHead>Reason</TableHead><TableHead>By</TableHead></TableRow></TableHeader>
              <TableBody>
                {(credits.data?.entries ?? []).map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="text-xs text-muted-foreground">{when(e.at_iso)}</TableCell>
                    <TableCell className="text-xs">{e.kind.replace("_", "-")}</TableCell>
                    <TableCell className={`text-right font-medium ${e.amount < 0 ? "text-destructive" : ""}`}>{e.amount < 0 ? "−" : "+"}${Math.abs(e.amount).toFixed(2)}</TableCell>
                    <TableCell className="text-sm">{e.note}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{e.by_email || "—"}</TableCell>
                  </TableRow>
                ))}
                {(credits.data?.entries ?? []).length === 0 && <TableRow><TableCell colSpan={5} className="text-center text-sm text-muted-foreground">No entry yet.</TableCell></TableRow>}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>

      <ReasonDialog open={dialog === "block"} onOpenChange={(v) => !v && setDialog(null)} title={`Block ${o?.name}`}
                    description="Its people stay signed in to Forge but every organisation and app route refuses; no build or turn starts." confirmText="Block" danger
                    pending={block.isPending} onConfirm={(r) => block.mutate(r)} />
      <ReasonDialog open={dialog === "remove"} onOpenChange={(v) => !v && setDialog(null)} title={`Remove ${o?.name}`}
                    description="Blocked and hidden from everyone; its data is kept and it can be reinstated. Purging is a separate, permanent step." confirmText="Remove" danger
                    pending={remove.isPending} onConfirm={(r) => remove.mutate(r)} />
      <TypedConfirmDialog open={dialog === "purge"} onOpenChange={(v) => !v && setDialog(null)} title={`Purge ${o?.name} for good`}
                          prompt="Every app, its database on the apps server, its Neon projects, its folders and every row go. Published Vercel deployments stay until removed by hand."
                          expected={o?.slug || ""} confirmText="Purge" pending={purge.isPending} onConfirm={() => purge.mutate()} />
      <AddMemberDialog open={dialog === "add"} onOpenChange={(v) => !v && setDialog(null)} orgName={o?.name || ""} pending={addMember.isPending}
                       onSubmit={(email, role) => addMember.mutate({ email, role })} />
      <CreditEntryDialog open={dialog === "entry"} onOpenChange={(v) => !v && setDialog(null)} orgName={o?.name || ""}
                         hasOpening={!!credits.data?.balance.known} pending={addEntry.isPending} onSubmit={(b) => addEntry.mutate(b)} />
      <TypedConfirmDialog open={!!deleting} onOpenChange={(v) => !v && setDeleting(null)} title={`Delete ${deleting?.name}`}
                          prompt="Its preview, its database on the apps server, its Neon projects, its folder and its rows go."
                          expected={deleting?.short_id || ""} confirmText="Delete" pending={deleteApp.isPending} onConfirm={() => deleting && deleteApp.mutate(deleting)} />
      <TeardownResult report={report} onClose={() => { setReport(null); if (purged) router.push("/admin/orgs"); }} />
    </div>
  );
}
