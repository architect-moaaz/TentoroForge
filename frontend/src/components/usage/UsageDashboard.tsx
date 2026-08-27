"use client";

/**
 * Admin usage analytics — what each app build actually cost.
 *
 * Reads GET /api/usage/summary (admin-gated: owner/admin of at least one
 * org). Every generation-pipeline agent phase records its token counts +
 * cost into the build-usage ledger; this page renders the aggregates:
 * total spend, per-app cost, per-pipeline-phase breakdown, daily trend,
 * and per-model split. Costs marked "est." are computed from token
 * counts × list price when the SDK didn't report a billed amount.
 */

import { useEffect, useState } from "react";
import { useAuthStore } from "@/stores/auth";
import { api, ApiError } from "@/lib/api";

type Row = {
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  events: number;
  project?: string;
  agent?: string;
  model?: string;
  last_ts?: number;
};

type Summary = {
  totals: {
    cost_usd: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_write_tokens: number;
    events: number;
    projects: number;
    estimated_events: number;
  };
  by_project: Row[];
  by_agent: Row[];
  by_model: Row[];
  daily: { day: string; cost_usd: number }[];
};

const fmtUsd = (v: number) =>
  v >= 100 ? `$${v.toFixed(0)}` : v >= 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(3)}`;
const fmtTok = (v: number) =>
  v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` :
  v >= 1_000 ? `${(v / 1_000).toFixed(1)}k` : `${v}`;

export function UsageDashboard() {
  const user = useAuthStore((s) => s.user) as
    | { orgs?: { org_id: string; role: string }[] }
    | null;
  const isAdmin = !!user?.orgs?.some(
    (o) => o.role === "owner" || o.role === "admin",
  );

  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // api.get sends the platform's Bearer token (raw fetch did not,
    // which 401'd even for logged-in admins).
    api
      .get<Summary>("/api/usage/summary")
      .then((d) => setData(d))
      .catch((e) => {
        if (e instanceof ApiError && e.status === 403) {
          setError("Admin role required.");
        } else {
          setError(e?.message ?? "Request failed");
        }
      })
      .finally(() => setLoading(false));
  }, []);

  if (user && !isAdmin)
    return (
      <div className="p-8 text-sm text-destructive">
        Admin role required to view usage analytics.
      </div>
    );
  if (loading)
    return <div className="p-8 text-sm text-muted-foreground">Loading usage…</div>;
  if (error || !data)
    return (
      <div className="p-8 text-sm text-destructive">
        {error ?? "Usage endpoint unreachable."}
      </div>
    );

  const t = data.totals;
  const totalTokens = t.input_tokens + t.output_tokens;
  const avgPerApp = t.projects ? t.cost_usd / t.projects : 0;
  const maxProject = Math.max(...data.by_project.map((r) => r.cost_usd), 0.0001);
  const maxAgent = Math.max(...data.by_agent.map((r) => r.cost_usd), 0.0001);
  const days = data.daily.slice(-14);
  const maxDay = Math.max(...days.map((d) => d.cost_usd), 0.0001);

  return (
    <div className="bg-background p-8 max-w-5xl mx-auto">
      <h1 className="text-2xl font-semibold mb-1">Build Cost &amp; Token Usage</h1>
      <p className="text-sm text-muted-foreground mb-6">
        What each generated app actually cost — recorded per pipeline agent
        phase during generation.
        {t.estimated_events > 0 && (
          <> {t.estimated_events} of {t.events} entries are estimated from
          token counts × list price (no billed amount reported).</>
        )}
      </p>

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
        <Stat label="Total spend" value={fmtUsd(t.cost_usd)} />
        <Stat
          label="Total tokens"
          value={fmtTok(totalTokens)}
          sub={`${fmtTok(t.input_tokens)} in · ${fmtTok(t.output_tokens)} out`}
        />
        <Stat label="Apps tracked" value={t.projects} sub={`${t.events} agent runs`} />
        <Stat label="Avg cost / app" value={fmtUsd(avgPerApp)} />
      </div>

      {/* Daily trend */}
      {days.length > 0 && (
        <section className="mb-8">
          <h2 className="text-sm font-semibold mb-3">Daily spend (last 14 days)</h2>
          <div className="flex items-end gap-1 h-28 rounded border bg-card p-3">
            {days.map((d) => (
              <div key={d.day} className="flex-1 flex flex-col items-center gap-1 min-w-0">
                <div
                  className="w-full rounded-sm bg-primary/70"
                  style={{ height: `${Math.max(4, (d.cost_usd / maxDay) * 80)}px` }}
                  title={`${d.day}: ${fmtUsd(d.cost_usd)}`}
                />
                <span className="text-[9px] text-muted-foreground truncate">
                  {d.day.slice(5)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Cost per app */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold mb-3">Cost per app</h2>
        <div className="rounded border bg-card divide-y">
          {data.by_project.length === 0 && (
            <p className="p-4 text-xs text-muted-foreground">
              No builds recorded yet — generate an app and its cost will appear here.
            </p>
          )}
          {data.by_project.map((r) => (
            <div key={r.project} className="p-3">
              <div className="flex items-center justify-between text-sm mb-1">
                <span className="font-mono">{r.project}</span>
                <span className="font-semibold tabular-nums">{fmtUsd(r.cost_usd)}</span>
              </div>
              <div className="h-1.5 rounded bg-muted overflow-hidden mb-1">
                <div
                  className="h-full bg-primary"
                  style={{ width: `${(r.cost_usd / maxProject) * 100}%` }}
                />
              </div>
              <p className="text-[11px] text-muted-foreground tabular-nums">
                {fmtTok(r.input_tokens)} in · {fmtTok(r.output_tokens)} out ·{" "}
                {r.events} agent runs
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Per pipeline phase */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold mb-3">Cost by pipeline phase</h2>
        <div className="rounded border bg-card divide-y">
          {data.by_agent.map((r) => (
            <div key={r.agent} className="flex items-center gap-3 p-2.5 text-xs">
              <span className="w-36 truncate font-medium">{r.agent}</span>
              <div className="flex-1 h-1.5 rounded bg-muted overflow-hidden">
                <div
                  className="h-full bg-primary/60"
                  style={{ width: `${(r.cost_usd / maxAgent) * 100}%` }}
                />
              </div>
              <span className="w-16 text-right tabular-nums font-semibold">
                {fmtUsd(r.cost_usd)}
              </span>
              <span className="w-24 text-right tabular-nums text-muted-foreground">
                {fmtTok(r.input_tokens + r.output_tokens)} tok
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* Per model */}
      <section>
        <h2 className="text-sm font-semibold mb-3">By model</h2>
        <div className="rounded border bg-card overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-muted-foreground border-b">
                <th className="p-2.5 font-medium">Model</th>
                <th className="p-2.5 font-medium text-right">Input</th>
                <th className="p-2.5 font-medium text-right">Output</th>
                <th className="p-2.5 font-medium text-right">Runs</th>
                <th className="p-2.5 font-medium text-right">Cost</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.by_model.map((r) => (
                <tr key={r.model}>
                  <td className="p-2.5 font-mono">{r.model}</td>
                  <td className="p-2.5 text-right tabular-nums">{fmtTok(r.input_tokens)}</td>
                  <td className="p-2.5 text-right tabular-nums">{fmtTok(r.output_tokens)}</td>
                  <td className="p-2.5 text-right tabular-nums">{r.events}</td>
                  <td className="p-2.5 text-right tabular-nums font-semibold">
                    {fmtUsd(r.cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: any; sub?: string }) {
  return (
    <div className="rounded border bg-card p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="text-2xl font-bold mt-1 tabular-nums">{value ?? "—"}</p>
      {sub && <p className="text-[11px] text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}
