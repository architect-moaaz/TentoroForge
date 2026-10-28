"use client";

/**
 * The agents — who on the team works how much, at what cost, how often their
 * work lands, and why it fails. Every agent is listed by name, the idle ones
 * too; a row opens that agent: who they are, their numbers, and the faults
 * they hit most. From `GET /api/admin/agents` (`services.agent_stats`): the
 * usage ledger for calls, spend and time, every app's run ledgers for steps,
 * failures, retries and the observer's repairs.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot, X } from "lucide-react";
import { Bars, HBars } from "@/components/usage/SpendPanel";
import { adminApi, adminKeys } from "@/lib/admin-api";
import type { AgentStat } from "@/lib/admin-types";
import { PERSONAS } from "@/lib/agentPersonas";

const PERIODS = [
  { id: "day", label: "Today" },
  { id: "week", label: "This week" },
  { id: "month", label: "This month" },
  { id: "year", label: "This year" },
] as const;

type SortKey = "name" | "steps" | "success_rate" | "failed" | "repairs" | "median_s" | "calls" | "cost_usd" | "busy_hours";

const usd = (n: number) => (n >= 100 ? `$${n.toFixed(0)}` : `$${n.toFixed(2)}`);
const pct = (n: number | null | undefined) => (n == null ? "—" : `${Math.round(n * 100)}%`);
function dur(s: number | null | undefined): string {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${(s / 60).toFixed(1)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "bad" | "good" }) {
  return (
    <div className="rounded-lg border bg-white dark:bg-slate-900 px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-xl font-semibold tabular-nums ${tone === "bad" ? "text-red-600" : tone === "good" ? "text-emerald-600" : ""}`}>{value}</p>
      {sub && <p className="text-[11px] text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}

function Card({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border bg-white dark:bg-slate-900 p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      {hint && <p className="text-xs text-muted-foreground mb-3">{hint}</p>}
      {children}
    </section>
  );
}

function landedTone(rate: number | null): string {
  if (rate == null) return "text-muted-foreground";
  if (rate >= 0.95) return "text-emerald-600";
  if (rate >= 0.8) return "text-amber-600";
  return "text-red-600";
}

function AgentDetail({ a, onClose }: { a: AgentStat; onClose: () => void }) {
  const intro = PERSONAS[a.agent]?.intro;
  return (
    <aside className="rounded-lg border bg-white dark:bg-slate-900 p-4 space-y-4" data-testid="agent-detail">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">{a.name}</h2>
          <p className="text-xs text-muted-foreground">{a.title}</p>
        </div>
        <button onClick={onClose} aria-label="Close" className="p-1 rounded hover:bg-muted"><X className="h-4 w-4" /></button>
      </div>
      {intro && <p className="text-sm leading-relaxed">{intro}</p>}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Tasks</dt><dd className="tabular-nums">{a.steps} ({a.done} landed, {a.failed} failed)</dd>
        <dt className="text-muted-foreground">Landed</dt><dd className={`tabular-nums ${landedTone(a.success_rate)}`}>{pct(a.success_rate)}</dd>
        <dt className="text-muted-foreground">Retries</dt><dd className="tabular-nums">{a.retries}</dd>
        <dt className="text-muted-foreground">Sent back by Otto</dt><dd className="tabular-nums">{a.repairs} ({a.unrepaired} left unrepaired)</dd>
        {a.agent === "observer" && (<><dt className="text-muted-foreground">Reviews given</dt><dd className="tabular-nums">{a.reviews} ({a.found} with findings)</dd></>)}
        <dt className="text-muted-foreground">Time per task</dt><dd className="tabular-nums">{dur(a.median_s)} median · {dur(a.p90_s)} p90</dd>
        <dt className="text-muted-foreground">Model calls</dt><dd className="tabular-nums">{a.calls} ({a.repair_calls} were repairs)</dd>
        <dt className="text-muted-foreground">Spend</dt><dd className="tabular-nums">{usd(a.cost_usd)}{a.cost_per_step_usd != null ? ` · ${usd(a.cost_per_step_usd)} per landed task` : ""}</dd>
        <dt className="text-muted-foreground">Busy</dt><dd className="tabular-nums">{a.busy_hours} h · {pct(a.utilization)} of the period</dd>
        <dt className="text-muted-foreground">Apps worked on</dt><dd className="tabular-nums">{a.apps}</dd>
        {a.runs_lost > 0 && (<><dt className="text-muted-foreground">Cut off by restarts</dt><dd className="tabular-nums text-red-600">{a.runs_lost}</dd></>)}
      </dl>
      <div>
        <h3 className="text-sm font-semibold mb-1.5">Why {a.name}&rsquo;s work failed</h3>
        {a.top_failures.length === 0 ? (
          <p className="text-sm text-muted-foreground">No failures in this period.</p>
        ) : (
          <ul className="space-y-1.5">
            {a.top_failures.map((f) => (
              <li key={f.reason} className="text-xs flex gap-2">
                <span className="tabular-nums font-semibold text-red-600 shrink-0">{f.count}×</span>
                <span className="break-words">{f.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

export default function AgentsPage() {
  const [period, setPeriod] = useState<string>("month");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "steps", desc: true });
  const [picked, setPicked] = useState<string | null>(null);
  const q = useQuery({ queryKey: adminKeys.agents(period), queryFn: () => adminApi.agents(period), refetchInterval: 60_000 });
  const report = q.data;

  const rows = useMemo(() => {
    const list = [...(report?.agents ?? [])];
    const { key, desc } = sort;
    list.sort((x, y) => {
      const a = x[key] ?? -1, b = y[key] ?? -1;
      const c = typeof a === "string" ? String(a).localeCompare(String(b)) : (a as number) - (b as number);
      return desc ? -c : c;
    });
    return list;
  }, [report, sort]);
  const chosen = rows.find((r) => r.agent === picked) ?? null;

  const head = (key: SortKey, label: string, right = true) => (
    <th className={`px-2 py-2 font-medium ${right ? "text-right" : "text-left"} cursor-pointer select-none hover:text-foreground`}
        onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== "name" }))}>
      {label}{sort.key === key ? (sort.desc ? " ↓" : " ↑") : ""}
    </th>
  );

  const t = report?.totals;
  return (
    <div className="p-6 space-y-5 max-w-[1400px]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Bot className="h-5 w-5" />
          <h1 className="text-lg font-semibold">Agents</h1>
          <span className="text-sm text-muted-foreground">who works how much, at what cost, and why their work fails</span>
        </div>
        <div className="flex gap-1 rounded-lg border p-0.5 bg-white dark:bg-slate-900">
          {PERIODS.map((p) => (
            <button key={p.id} onClick={() => setPeriod(p.id)}
                    className={`px-3 py-1 text-sm rounded-md ${period === p.id ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900" : "hover:bg-muted"}`}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {q.isError && <p className="text-sm text-red-600">The agents could not be read: {(q.error as Error)?.message}</p>}
      {q.isLoading && <p className="text-sm text-muted-foreground">Reading every app&rsquo;s runs…</p>}

      {t && (
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
          <Kpi label="Agents at work" value={`${t.active_agents} of ${report!.agents.length}`} />
          <Kpi label="Tasks" value={String(t.steps)} sub={`${t.done} landed`} />
          <Kpi label="Landed" value={pct(t.success_rate)} tone={t.success_rate != null && t.success_rate < 0.9 ? "bad" : "good"} />
          <Kpi label="Failed" value={String(t.failed)} tone={t.failed ? "bad" : undefined} sub={`${t.retries} retries`} />
          <Kpi label="Sent back to redo" value={String(t.repairs)} sub={`${t.unrepaired} left unrepaired`} />
          <Kpi label="Cut off by restarts" value={String(t.runs_lost)} tone={t.runs_lost ? "bad" : undefined} />
          <Kpi label="Spend" value={usd(t.cost_usd)} sub={`${t.calls} model calls`} />
          <Kpi label="Busy" value={`${t.busy_hours} h`} sub="time in model calls" />
        </div>
      )}

      {report && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Spend per day" hint="Every agent's model calls, by the day they were made.">
            <Bars series={report.daily.map((d) => ({ label: d.day.slice(5), value: d.cost_usd }))} />
          </Card>
          <Card title="Spend by agent" hint="Click an agent to open them.">
            <HBars rows={rows.filter((r) => r.cost_usd > 0).sort((a, b) => b.cost_usd - a.cost_usd).slice(0, 12)
                       .map((r) => ({ key: r.agent, label: `${r.name} (${r.title})`, value: r.cost_usd, sub: `${r.calls} calls` }))}
                   onPick={(key) => setPicked(key)} />
          </Card>
        </div>
      )}

      {report && (
        <div className={`grid gap-4 ${chosen ? "lg:grid-cols-[1fr_380px]" : ""}`}>
          <section className="rounded-lg border bg-white dark:bg-slate-900 overflow-x-auto">
            <table className="w-full text-sm" data-testid="agents-table">
              <thead className="text-xs text-muted-foreground border-b">
                <tr>
                  {head("name", "Agent", false)}
                  {head("steps", "Tasks")}
                  {head("success_rate", "Landed")}
                  {head("failed", "Failed")}
                  {head("repairs", "Sent back")}
                  {head("median_s", "Median time")}
                  {head("calls", "Calls")}
                  {head("cost_usd", "Spend")}
                  {head("busy_hours", "Busy")}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const idle = !r.calls && !r.steps;
                  return (
                    <tr key={r.agent} onClick={() => setPicked(r.agent === picked ? null : r.agent)}
                        className={`border-b last:border-0 cursor-pointer hover:bg-muted/50 ${r.agent === picked ? "bg-muted/70" : ""} ${idle ? "opacity-50" : ""}`}>
                      <td className="px-2 py-2">
                        <span className="font-medium">{r.name}</span>
                        <span className="text-xs text-muted-foreground"> · {r.title}</span>
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">{r.steps || (r.reviews ? `${r.reviews} reviews` : "—")}</td>
                      <td className={`px-2 py-2 text-right tabular-nums ${landedTone(r.success_rate)}`}>{pct(r.success_rate)}</td>
                      <td className={`px-2 py-2 text-right tabular-nums ${r.failed ? "text-red-600 font-medium" : ""}`}>{r.failed || "—"}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{r.repairs || "—"}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{dur(r.median_s)}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{r.calls || "—"}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{r.cost_usd ? usd(r.cost_usd) : "—"}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{r.busy_hours ? `${r.busy_hours} h` : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
          {chosen && <AgentDetail a={chosen} onClose={() => setPicked(null)} />}
        </div>
      )}
    </div>
  );
}
