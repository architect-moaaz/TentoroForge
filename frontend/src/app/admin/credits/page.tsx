"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { adminApi, adminKeys } from "@/lib/admin-api";
import type { CreditKind, Limits, OrgBalanceRow } from "@/lib/admin-types";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { CreditEntryDialog } from "@/components/admin/CreditEntryDialog";
import { LimitsEditor } from "@/components/admin/LimitsEditor";
import { when } from "@/components/admin/PeopleTable";
import { SpendPanel } from "@/components/usage/SpendPanel";

function money(v: number | null | undefined): string {
  return v == null ? "—" : `$${v.toFixed(2)}`;
}

type PlatformStanding = { balance_total_usd: number; orgs_known: number; orgs: number; platform_limits: Limits; build_estimate_usd: number; spent: Record<string, number> };

export default function AdminCreditsPage() {
  const qc = useQueryClient();
  const credits = useQuery({ queryKey: adminKeys.credits, queryFn: adminApi.credits });
  const platform = useQuery({ queryKey: ["admin", "credits", "standing"], queryFn: () => api.get<PlatformStanding>("/api/admin/credits/standing") });
  const [entryFor, setEntryFor] = useState<OrgBalanceRow | null>(null);
  const [limitsFor, setLimitsFor] = useState<OrgBalanceRow | null>(null);

  const refresh = () => { qc.invalidateQueries({ queryKey: ["admin", "credits"] }); qc.invalidateQueries({ queryKey: ["admin", "audit"] }); };
  const fail = (e: unknown, what: string) => toast.error(e instanceof ApiError ? e.message : what);
  const addEntry = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { amount_usd: number; kind: CreditKind; note: string } }) => adminApi.addEntry(id, body),
    onSuccess: () => { toast.success("Entry recorded"); refresh(); setEntryFor(null); }, onError: (e) => fail(e, "Not recorded"),
  });
  const setLimits = useMutation({
    mutationFn: ({ kind, id, limits }: { kind: string; id: string; limits: Limits }) => adminApi.setLimits(kind, id, limits),
    onSuccess: () => { toast.success("Limits saved"); refresh(); setLimitsFor(null); }, onError: (e) => fail(e, "Limits not saved"),
  });

  const rows = credits.data?.orgs ?? [];
  const p = platform.data;
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Credits</h1>
        <p className="text-sm text-muted-foreground">
          Each organisation holds its own credit. One with no entry is unknown — nothing is refused for a balance nobody recorded; only limits apply.
          A build is expected to cost about {money(credits.data?.build_estimate_usd)}.
        </p>
      </div>

      {p && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label="Credit held, every known organisation" value={money(p.balance_total_usd)} sub={`${p.orgs_known} of ${p.orgs} organisations have an entry`} />
          <Kpi label="Spent today" value={money(p.spent.day)} sub={`this week ${money(p.spent.week)}`} />
          <Kpi label="Spent this month" value={money(p.spent.month)} sub={`this year ${money(p.spent.year)}`} />
          <Kpi label="A build is expected to cost" value={money(p.build_estimate_usd)} sub="median of recent builds" />
        </div>
      )}

      <div className="rounded-lg border bg-white dark:bg-slate-900">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Organisation</TableHead>
              <TableHead className="text-right">Credit</TableHead>
              <TableHead className="text-right">Spent</TableHead>
              <TableHead className="text-right">Balance</TableHead>
              <TableHead>Limits</TableHead>
              <TableHead>Last entry</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((o) => (
              <TableRow key={o.org_id} data-testid={`credit-${o.slug}`}>
                <TableCell>
                  <Link href={`/admin/orgs/${o.org_id}`} className="font-medium hover:underline">{o.name}</Link>
                  <div className="text-xs"><StatusBadge kind="org" status={o.status} /></div>
                </TableCell>
                <TableCell className="text-right">{o.known ? money(o.credit_usd) : "—"}</TableCell>
                <TableCell className="text-right">{money(o.known ? o.spent_usd : o.spent_all_time_usd)}{!o.known && <span className="block text-[10px] text-muted-foreground">all time</span>}</TableCell>
                <TableCell className={`text-right font-medium ${o.known && (o.balance_usd ?? 0) <= 0 ? "text-destructive" : ""}`}>
                  {o.known ? money(o.balance_usd) : <span className="text-xs font-normal text-muted-foreground">unknown — limits only</span>}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {Object.keys(o.limits).length ? Object.entries(o.limits).map(([per, v]) => `${per} ${money(v)}`).join(" · ") : "none"}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {o.last_entry ? `${o.last_entry.kind.replace("_", "-")} ${money(o.last_entry.amount)} · ${when(o.last_entry.at_iso)}` : "—"}
                </TableCell>
                <TableCell className="space-x-2 text-right text-xs">
                  <button className="text-primary hover:underline" onClick={() => setEntryFor(o)}>Add entry</button>
                  <button className="text-primary hover:underline" onClick={() => setLimitsFor(o)}>Limits</button>
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && <TableRow><TableCell colSpan={7} className="text-center text-sm text-muted-foreground">No organisation yet.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {limitsFor && (
          <LimitsEditor key={limitsFor.org_id} title={`Limits for ${limitsFor.name}`} initial={limitsFor.limits} pending={setLimits.isPending}
                        onSave={(l) => setLimits.mutate({ kind: "org", id: limitsFor.org_id, limits: l })} />
        )}
        <LimitsEditor title="Platform-wide limits (every organisation together)" initial={p?.platform_limits ?? {}}
                      pending={setLimits.isPending} onSave={(l) => setLimits.mutate({ kind: "platform", id: "", limits: l })} />
      </div>

      <SpendPanel heading="Spend across the platform" />

      <CreditEntryDialog open={!!entryFor} onOpenChange={(v) => !v && setEntryFor(null)} orgName={entryFor?.name || ""}
                         hasOpening={!!entryFor?.known} pending={addEntry.isPending}
                         onSubmit={(body) => entryFor && addEntry.mutate({ id: entryFor.org_id, body })} />
    </div>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border bg-white p-4 dark:bg-slate-900">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums">{value}</p>
      {sub ? <p className="mt-0.5 text-[11px] text-muted-foreground">{sub}</p> : null}
    </div>
  );
}
