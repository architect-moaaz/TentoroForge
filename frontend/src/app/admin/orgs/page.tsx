"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { adminApi, adminKeys } from "@/lib/admin-api";
import { OrgsTable } from "@/components/admin/OrgsTable";

function AdminOrgsPageInner() {
  const params = useSearchParams();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState(params.get("status") || "all");
  const [page, setPage] = useState(1);
  const filter = status === "all" ? "" : status;
  const orgs = useQuery({ queryKey: adminKeys.orgs(q, filter, page), queryFn: () => adminApi.orgs(q, filter, page) });
  const total = orgs.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / (orgs.data?.page_size ?? 50)));
  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <h1 className="text-2xl font-bold tracking-tight">Organisations</h1>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-72">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-8" placeholder="Name or slug" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        </div>
        <Select value={status} onValueChange={(v) => { setStatus(v); setPage(1); }}>
          <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Every status</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="blocked">Blocked</SelectItem>
            <SelectItem value="removed">Removed</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">{total} organisation{total === 1 ? "" : "s"}</span>
      </div>
      <div className="rounded-lg border bg-white dark:bg-slate-900">
        <OrgsTable rows={orgs.data?.items ?? []} />
      </div>
      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-xs">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <span>{page} / {pages}</span>
          <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
    </div>
  );
}

// useSearchParams needs a Suspense boundary above it for the static shell.
export default function AdminOrgsPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      <AdminOrgsPageInner />
    </Suspense>
  );
}
