"use client";

/**
 * An organisation's standing, for its owners and admins: the credit it
 * holds against what it has spent, the limits that cover it, and what a
 * build is expected to cost — the same figures the door uses when it
 * refuses a build or a turn with "Not started: …". An organisation with
 * no credit entry has an unknown balance and is held only by its limits.
 */

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { OrgSpend } from "@/lib/admin-types";

const usd = (v: number | null | undefined) => (v == null ? "—" : `$${v.toFixed(2)}`);

export function OrgBalanceCard({ orgId }: { orgId: string }) {
  const spend = useQuery({
    queryKey: ["org", orgId, "spend"],
    queryFn: () => api.get<OrgSpend>(`/api/orgs/${orgId}/spend`),
    retry: false,
  });
  if (spend.isError || !spend.data) return null;
  const { balance, limits, build_estimate_usd, report } = spend.data;
  const covering = limits.filter((l) => l.limit_usd != null);
  return (
    <section className="mb-8 rounded-lg border bg-card p-4" data-testid="org-balance">
      <div className="grid gap-4 md:grid-cols-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Balance</p>
          {balance.known ? (
            <>
              <p className={`mt-1 text-2xl font-bold tabular-nums ${(balance.balance_usd ?? 0) <= 0 ? "text-destructive" : ""}`}>{usd(balance.balance_usd)}</p>
              <p className="text-[11px] text-muted-foreground">{usd(balance.credit_usd)} credited · {usd(balance.spent_usd)} spent since {balance.since?.slice(0, 10)}</p>
            </>
          ) : (
            <>
              <p className="mt-1 text-lg font-semibold">unknown</p>
              <p className="text-[11px] text-muted-foreground">no credit recorded (limits only)</p>
            </>
          )}
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Spent this month</p>
          <p className="mt-1 text-2xl font-bold tabular-nums">{usd(report.total.cost_usd)}</p>
          <p className="text-[11px] text-muted-foreground">a build is expected to cost about {usd(build_estimate_usd)}</p>
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Limits</p>
          {covering.length === 0 ? (
            <p className="mt-1 text-sm text-muted-foreground">none set</p>
          ) : (
            <ul className="mt-1 space-y-0.5 text-sm">
              {covering.map((l) => (
                <li key={`${l.scope}:${l.period}`} className="flex justify-between gap-2 tabular-nums">
                  <span className="text-muted-foreground">{l.scope === "platform" ? "platform" : l.scope.split(":")[0]} · {l.period}</span>
                  <span className={l.left_usd != null && l.left_usd <= 0 ? "text-destructive" : ""}>{usd(l.left_usd)} left of {usd(l.limit_usd)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <p className="mt-3 text-[11px] text-muted-foreground">A build or a Smith turn the balance or a limit cannot cover is not started; the platform's administrator records credit and sets limits.</p>
    </section>
  );
}
