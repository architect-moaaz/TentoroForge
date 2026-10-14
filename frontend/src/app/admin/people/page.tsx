"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { adminApi, adminKeys } from "@/lib/admin-api";
import type { AdminPerson } from "@/lib/admin-types";
import { PeopleTable } from "@/components/admin/PeopleTable";
import { ReasonDialog } from "@/components/admin/ReasonDialog";
import { useAuthStore } from "@/stores/auth";

function AdminPeoplePageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const impersonate = useAuthStore((s) => s.impersonate);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [disabling, setDisabling] = useState<AdminPerson | null>(null);
  const people = useQuery({ queryKey: adminKeys.people(q, page), queryFn: () => adminApi.people(q, page) });

  useEffect(() => {
    if (params.get("expired")) toast.info("The impersonation session ended; you are back in the cockpit.");
  }, [params]);

  const refresh = () => { qc.invalidateQueries({ queryKey: ["admin", "people"] }); qc.invalidateQueries({ queryKey: ["admin", "audit"] }); };
  const fail = (e: unknown, what: string) => toast.error(e instanceof ApiError ? e.message : what);
  const disable = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => adminApi.disable(id, reason),
    onSuccess: () => { toast.success("Login disabled"); refresh(); setDisabling(null); }, onError: (e) => fail(e, "Not disabled"),
  });
  const enable = useMutation({ mutationFn: adminApi.enable, onSuccess: () => { toast.success("Login enabled"); refresh(); }, onError: (e) => fail(e, "Not enabled") });
  const grant = useMutation({ mutationFn: adminApi.grant, onSuccess: () => { toast.success("Super admin granted"); refresh(); }, onError: (e) => fail(e, "Not granted") });
  const revoke = useMutation({ mutationFn: adminApi.revoke, onSuccess: () => { toast.success("Super admin revoked"); refresh(); }, onError: (e) => fail(e, "Not revoked") });

  async function onImpersonate(p: AdminPerson) {
    try {
      const org = await impersonate(p.id);
      qc.clear();
      router.push(org ? `/org/${org}` : "/");
    } catch (e) {
      fail(e, "Could not impersonate");
    }
  }

  const total = people.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / (people.data?.page_size ?? 50)));
  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <h1 className="text-2xl font-bold tracking-tight">People</h1>
      <div className="flex items-center gap-3">
        <div className="relative w-72">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-8" placeholder="Email or name" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        </div>
        <span className="text-xs text-muted-foreground">{total} {total === 1 ? "person" : "people"}</span>
      </div>
      <div className="rounded-lg border bg-white dark:bg-slate-900">
        <PeopleTable rows={people.data?.items ?? []} selfId={me?.id || ""}
                     onDisable={setDisabling} onEnable={(p) => enable.mutate(p.id)}
                     onGrant={(p) => { if (window.confirm(`Make ${p.email} a super admin of the whole platform?`)) grant.mutate(p.id); }}
                     onRevoke={(p) => { if (window.confirm(`Revoke ${p.email}'s super admin role?`)) revoke.mutate(p.id); }}
                     onImpersonate={onImpersonate} />
      </div>
      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-xs">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <span>{page} / {pages}</span>
          <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
      <ReasonDialog open={!!disabling} onOpenChange={(v) => !v && setDisabling(null)} title={`Disable ${disabling?.email}`}
                    description="Their next request is refused, signing in is refused, and so is a refresh; enabling restores everything."
                    confirmText="Disable login" danger pending={disable.isPending}
                    onConfirm={(reason) => disabling && disable.mutate({ id: disabling.id, reason })} />
    </div>
  );
}

// useSearchParams needs a Suspense boundary above it for the static shell.
export default function AdminPeoplePage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      <AdminPeoplePageInner />
    </Suspense>
  );
}
