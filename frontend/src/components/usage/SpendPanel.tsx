"use client";

/**
 * Spend — who spent what, through which agent, by day / week / month /
 * year, with a drill-down: click an application, a person or an agent and
 * the whole panel narrows to it, with a breadcrumb back.
 *
 * Reads GET /api/spend/report and /api/spend/standing. Mounted with a
 * `scope` it is pinned to that organisation, person or application (the
 * cockpit's organisation page, an organisation's own usage settings);
 * without one it offers the platform, the person's own spend and each of
 * their organisations. Credit and limits are written elsewhere — in the
 * cockpit's Credits page — so this panel only reads.
 */

import { agentLabel } from "@/lib/agentPersonas";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuthStore } from "@/stores/auth";
import { api } from "@/lib/api";

type Bucket = { cost_usd: number; calls: number; input_tokens: number; output_tokens: number };
type Report = {
  period: string; from: string; to: string;
  scope: { org: string; user: string; project: string; agent: string };
  total: Bucket;
  by_agent: (Bucket & { agent: string })[];
  by_project: (Bucket & { project: string; name: string })[];
  by_user: (Bucket & { user: string })[];
  by_model: (Bucket & { model: string })[];
  by_phase: (Bucket & { phase: string })[];
  by_day: { day: string; cost_usd: number }[];
  by_hour: { hour: string; cost_usd: number }[];
};
type Standing = {
  balance: { known: boolean; credit_usd: number; spent_usd: number; balance_usd: number | null; since: string | null };
  limits: { scope: string; period: string; spent_usd: number; limit_usd: number | null; left_usd: number | null }[];
  build_estimate_usd: number;
};
type Drill = { kind: "project" | "person" | "agent"; id: string; label: string };

export type SpendScope = { org?: string; person?: string; project?: string; label?: string };

const PERIODS = ["day", "week", "month", "year"] as const;
type Period = (typeof PERIODS)[number];
export const usd = (v: number | null | undefined) =>
  v == null ? "—" : v >= 100 ? `$${v.toFixed(0)}` : v >= 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(3)}`;
const PALETTE = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#65a30d", "#ea580c", "#4f46e5", "#0d9488", "#9333ea"];
const appLabel = (r: { project: string; name?: string }) => (r.name ? `${r.name} · ${r.project}` : r.project);

export function SpendPanel({ scope, heading = "Spend" }: { scope?: SpendScope; heading?: string }) {
  const user = useAuthStore((s) => s.user) as {
    email?: string; platform_role?: string | null; orgs?: { org_id: string; role: string; org_name?: string }[];
  } | null;
  const isSuper = user?.platform_role === "super_admin";
  const isAdmin = isSuper || !!user?.orgs?.some((o) => o.role === "owner" || o.role === "admin");
  const orgs = user?.orgs ?? [];
  const pinned = !!scope;

  const [period, setPeriod] = useState<Period>("month");
  const [at, setAt] = useState<string>("");
  const [picked, setPicked] = useState<string>(isSuper ? "platform" : "me");
  const [drill, setDrill] = useState<Drill[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [standing, setStanding] = useState<Standing | null>(null);
  const [error, setError] = useState<string | null>(null);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (scope) {
      if (scope.org) p.set("org", scope.org);
      if (scope.person) p.set("person", scope.person);
      if (scope.project) p.set("project", scope.project);
    } else if (picked === "me") p.set("person", "me");
    else if (picked.startsWith("org:")) p.set("org", picked.slice(4));
    for (const d of drill) {
      if (d.kind === "project") p.set("project", d.id);
      if (d.kind === "person") p.set("person", d.id);
      if (d.kind === "agent") p.set("agent", d.id);
    }
    return p;
  }, [scope, picked, drill]);

  const load = useCallback(() => {
    setError(null);
    const r = new URLSearchParams(query);
    r.set("period", period);
    if (at) r.set("at", at);
    const s = new URLSearchParams(query);
    s.delete("agent");
    Promise.all([
      api.get<Report>(`/api/spend/report?${r.toString()}`),
      api.get<Standing>(`/api/spend/standing?${s.toString()}`),
    ])
      .then(([rep, st]) => { setReport(rep); setStanding(st); })
      .catch((e) => setError(e?.message ?? "Request failed"));
  }, [query, period, at]);

  useEffect(() => { load(); }, [load]);

  const into = (d: Drill) => setDrill((cur) => (cur.some((x) => x.kind === d.kind) ? cur : [...cur, d]));
  const backTo = (i: number) => setDrill((cur) => cur.slice(0, i));

  const bal = standing?.balance;
  const namesOrg = !!(scope?.org || picked.startsWith("org:"));
  const series = period === "day" && report?.by_hour?.length
    ? report.by_hour.map((h) => ({ label: h.hour, value: h.cost_usd }))
    : (report?.by_day ?? []).map((d) => ({ label: d.day.slice(5), value: d.cost_usd }));
  const scopeLabel = scope
    ? scope.label ?? (scope.org ? `organisation ${scope.org.slice(0, 8)}` : scope.person ? `person ${scope.person}` : `application ${scope.project}`)
    : picked === "me" ? `me (${user?.email ?? ""})` : picked === "platform" ? "whole platform"
    : `organisation ${orgs.find((o) => `org:${o.org_id}` === picked)?.org_name ?? picked.slice(4, 12)}`;

  return (
    <section className="mb-10">
      <div className="flex flex-wrap items-end gap-3 mb-3">
        <div>
          <h2 className="text-lg font-semibold">{heading}</h2>
          <p className="text-xs text-muted-foreground">Who spent what, through which agent. Click an application, a person or an agent to drill in.</p>
        </div>
        <div className="ml-auto flex flex-wrap gap-2 items-center">
          {!pinned && (
            <select className="rounded border bg-background px-2 py-1 text-sm" value={picked}
                    onChange={(e) => { setPicked(e.target.value); setDrill([]); }}>
              {isSuper && <option value="platform">Whole platform</option>}
              <option value="me">Me ({user?.email ?? "me"})</option>
              {isAdmin && orgs.filter((o) => isSuper || o.role === "owner" || o.role === "admin").map((o) => (
                <option key={o.org_id} value={`org:${o.org_id}`}>Organisation {o.org_name ?? o.org_id.slice(0, 8)}</option>
              ))}
            </select>
          )}
          <div className="flex rounded border overflow-hidden">
            {PERIODS.map((p) => (
              <button key={p} onClick={() => setPeriod(p)}
                      className={`px-3 py-1 text-sm capitalize ${period === p ? "bg-primary text-primary-foreground" : "bg-background"}`}>
                {p}
              </button>
            ))}
          </div>
          <input type="date" className="rounded border bg-background px-2 py-1 text-sm" value={at}
                 onChange={(e) => setAt(e.target.value)} title="Any day inside the period" />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1 text-sm mb-4">
        <button className={`rounded px-2 py-0.5 ${drill.length ? "text-primary hover:underline" : "font-medium"}`} onClick={() => backTo(0)}>
          {scopeLabel}
        </button>
        {drill.map((d, i) => (
          <span key={d.kind} className="flex items-center gap-1">
            <span className="text-muted-foreground">›</span>
            <button className={`rounded px-2 py-0.5 ${i < drill.length - 1 ? "text-primary hover:underline" : "font-medium"}`}
                    onClick={() => backTo(i + 1)}>
              {d.kind === "project" ? "application" : d.kind} {d.label}
            </button>
          </span>
        ))}
        {report && <span className="ml-2 text-xs text-muted-foreground">{report.from.slice(0, 10)} → {report.to.slice(0, 10)}</span>}
      </div>

      {error && <p className="text-sm text-destructive mb-3">{error}</p>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Kpi label={`Spent this ${period}`} value={usd(report?.total.cost_usd)} sub={report ? `${report.total.calls} calls` : ""} />
        {namesOrg ? (
          <Kpi label="Organisation balance" value={bal?.known ? usd(bal.balance_usd) : "unknown"}
               sub={bal?.known ? `${usd(bal.credit_usd)} credited · ${usd(bal.spent_usd)} spent since ${bal.since?.slice(0, 10)}` : "no credit recorded — limits only"} />
        ) : (
          <Kpi label="Calls" value={report ? String(report.total.calls) : "—"} sub="model calls in the period" />
        )}
        <Kpi label="A build is expected to cost" value={usd(standing?.build_estimate_usd)} sub="median of recent builds" />
        <Kpi label="Tokens" value={report ? `${Math.round((report.total.input_tokens + report.total.output_tokens) / 1000)}k` : "—"}
             sub={report ? `${Math.round(report.total.input_tokens / 1000)}k in · ${Math.round(report.total.output_tokens / 1000)}k out` : ""} />
      </div>

      <Card title={period === "day" ? "By hour (UTC)" : "By day"}>
        <Bars series={series} />
      </Card>

      <div className="grid md:grid-cols-2 gap-4 my-4">
        <Card title="By agent" hint={drill.some((d) => d.kind === "agent") ? "" : "click to drill in"}>
          <HBars rows={(report?.by_agent ?? []).slice(0, 14).map((r) => ({ key: r.agent, label: agentLabel(r.agent), value: r.cost_usd, sub: `${r.calls} calls` }))}
                 onPick={drill.some((d) => d.kind === "agent") ? undefined : (k) => into({ kind: "agent", id: k, label: k })} />
        </Card>
        <Card title="By application" hint={drill.some((d) => d.kind === "project") || scope?.project ? "" : "click to drill in"}>
          <Donut rows={(report?.by_project ?? []).map((r) => ({ key: r.project, label: appLabel(r), value: r.cost_usd, sub: `${r.calls} calls` }))}
                 onPick={drill.some((d) => d.kind === "project") || scope?.project ? undefined : (k, label) => into({ kind: "project", id: k, label })} />
        </Card>
        <Card title="By person" hint={drill.some((d) => d.kind === "person") || scope?.person ? "" : "click to drill in"}>
          <Donut rows={(report?.by_user ?? []).map((r) => ({ key: r.user, label: r.user || "unattributed", value: r.cost_usd, sub: `${r.calls} calls` }))}
                 onPick={drill.some((d) => d.kind === "person") || scope?.person ? undefined : (k, label) => (k ? into({ kind: "person", id: k, label }) : undefined)} />
        </Card>
        <Card title="Build vs change · by model">
          <HBars rows={[...(report?.by_phase ?? []).map((r) => ({ key: `phase:${r.phase}`, label: r.phase === "build" ? "building" : r.phase === "change" ? "changes after" : r.phase, value: r.cost_usd, sub: `${r.calls} calls` })),
                        ...(report?.by_model ?? []).map((r) => ({ key: `model:${r.model}`, label: r.model, value: r.cost_usd, sub: `${r.calls} calls` }))]} />
        </Card>
      </div>

      {standing && (
        <Card title="Limits that cover this scope">
          <Table head={["Scope", "Period", "Spent", "Limit", "Left"]}
                 rows={standing.limits.filter((l) => l.limit_usd != null || l.spent_usd > 0).map((l) => [
                   l.scope === "platform" ? "Whole platform" : scopeName(l.scope, report, orgs), l.period, usd(l.spent_usd),
                   l.limit_usd == null ? "none" : usd(l.limit_usd), l.left_usd == null ? "—" : usd(l.left_usd)])} />
        </Card>
      )}
    </section>
  );
}

function scopeName(scope: string, report: Report | null, orgs: { org_id: string; org_name?: string }[]): string {
  const [kind, id] = [scope.split(":", 1)[0], scope.slice(scope.indexOf(":") + 1)];
  if (kind === "org") return `Organisation ${orgs.find((o) => o.org_id === id)?.org_name ?? id.slice(0, 8)}`;
  if (kind === "project") { const r = report?.by_project.find((p) => p.project === id); return `Application ${r ? appLabel(r) : id}`; }
  if (kind === "user") return `Person ${id}`;
  return scope;
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded border bg-card p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="text-2xl font-bold mt-1 tabular-nums">{value}</p>
      {sub ? <p className="text-[11px] text-muted-foreground mt-0.5">{sub}</p> : null}
    </div>
  );
}

function Card({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="rounded border bg-card p-4">
      <div className="flex items-baseline justify-between mb-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {hint ? <span className="text-[11px] text-muted-foreground">{hint}</span> : null}
      </div>
      {children}
    </div>
  );
}

/** Vertical bars over time with the value on hover and the top on the axis. */
export function Bars({ series }: { series: { label: string; value: number }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!series.length) return <p className="text-sm text-muted-foreground">Nothing in this period.</p>;
  const W = 720, H = 160, padL = 44, padB = 22, padT = 10;
  const max = Math.max(...series.map((s) => s.value), 0.01);
  const bw = (W - padL - 8) / series.length;
  const ticks = [0, max / 2, max];
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-40" onMouseLeave={() => setHover(null)}>
        {ticks.map((t, i) => {
          const y = padT + (H - padT - padB) * (1 - t / max);
          return (
            <g key={i}>
              <line x1={padL} x2={W - 4} y1={y} y2={y} stroke="currentColor" strokeOpacity={0.12} />
              <text x={padL - 6} y={y + 3} textAnchor="end" fontSize={10} fill="currentColor" fillOpacity={0.6}>{usd(t)}</text>
            </g>
          );
        })}
        {series.map((s, i) => {
          const h = Math.max(2, (H - padT - padB) * (s.value / max));
          const x = padL + i * bw + bw * 0.15;
          const y = H - padB - h;
          const every = Math.ceil(series.length / 12);
          return (
            <g key={s.label} onMouseEnter={() => setHover(i)}>
              <rect x={x} y={y} width={bw * 0.7} height={h} rx={2} fill={PALETTE[0]} fillOpacity={hover === i ? 1 : 0.75} />
              {i % every === 0 && (
                <text x={x + bw * 0.35} y={H - 6} textAnchor="middle" fontSize={10} fill="currentColor" fillOpacity={0.6}>{s.label}</text>
              )}
              {hover === i && (
                <text x={Math.min(Math.max(x + bw * 0.35, padL + 30), W - 40)} y={Math.max(y - 4, 10)} textAnchor="middle" fontSize={11} fontWeight={600} fill="currentColor">
                  {s.label}: {usd(s.value)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Horizontal bars with labels; clickable when `onPick` is given. */
export function HBars({ rows, onPick }: { rows: { key: string; label: string; value: number; sub?: string }[]; onPick?: (key: string, label: string) => void }) {
  if (!rows.length) return <p className="text-sm text-muted-foreground">Nothing in this period.</p>;
  const max = Math.max(...rows.map((r) => r.value), 0.0001);
  const total = rows.reduce((a, r) => a + r.value, 0) || 1;
  return (
    <ul className="space-y-1.5">
      {rows.map((r, i) => (
        <li key={r.key}>
          <button disabled={!onPick} onClick={() => onPick?.(r.key, r.label)}
                  className={`w-full text-left ${onPick ? "hover:bg-muted/60 rounded cursor-pointer" : "cursor-default"} px-1 py-0.5`}>
            <div className="flex items-baseline justify-between text-xs">
              <span className="truncate font-medium">{r.label}</span>
              <span className="tabular-nums text-muted-foreground ml-2 whitespace-nowrap">{usd(r.value)} · {Math.round((r.value / total) * 100)}%{r.sub ? ` · ${r.sub}` : ""}</span>
            </div>
            <div className="h-2 rounded bg-muted mt-0.5">
              <div className="h-2 rounded" style={{ width: `${Math.max(1.5, (r.value / max) * 100)}%`, background: PALETTE[i % PALETTE.length] }} />
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** A donut with its legend; clickable when `onPick` is given. */
export function Donut({ rows, onPick }: { rows: { key: string; label: string; value: number; sub?: string }[]; onPick?: (key: string, label: string) => void }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!rows.length) return <p className="text-sm text-muted-foreground">Nothing in this period.</p>;
  const total = rows.reduce((a, r) => a + r.value, 0) || 1;
  const shown = rows.slice(0, 10);
  const rest = rows.slice(10).reduce((a, r) => a + r.value, 0);
  const slices = rest > 0 ? [...shown, { key: "", label: `${rows.length - 10} more`, value: rest }] : shown;
  const R = 54, r = 34, C = 64;
  let angle = -Math.PI / 2;
  const arcs = slices.map((s, i) => {
    const a0 = angle, a1 = angle + (s.value / total) * Math.PI * 2;
    angle = a1;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const p = (rad: number, a: number) => `${C + rad * Math.cos(a)} ${C + rad * Math.sin(a)}`;
    const d = `M ${p(R, a0)} A ${R} ${R} 0 ${large} 1 ${p(R, a1)} L ${p(r, a1)} A ${r} ${r} 0 ${large} 0 ${p(r, a0)} Z`;
    return { ...s, d, color: PALETTE[i % PALETTE.length], i };
  });
  const focus = hover != null ? arcs[hover] : null;
  return (
    <div className="flex gap-4 items-start">
      <svg viewBox="0 0 128 128" className="w-32 h-32 shrink-0" onMouseLeave={() => setHover(null)}>
        {arcs.map((a) => (
          <path key={a.i} d={a.d} fill={a.color} fillOpacity={hover == null || hover === a.i ? 1 : 0.35}
                className={onPick && a.key ? "cursor-pointer" : ""}
                onMouseEnter={() => setHover(a.i)} onClick={() => a.key && onPick?.(a.key, a.label)} />
        ))}
        <text x={C} y={C - 2} textAnchor="middle" fontSize={11} fontWeight={700} fill="currentColor">
          {focus ? usd(focus.value) : usd(total)}
        </text>
        <text x={C} y={C + 11} textAnchor="middle" fontSize={8} fill="currentColor" fillOpacity={0.6}>
          {focus ? `${Math.round((focus.value / total) * 100)}%` : "total"}
        </text>
      </svg>
      <ul className="flex-1 space-y-1 min-w-0">
        {arcs.map((a) => (
          <li key={a.i}>
            <button disabled={!onPick || !a.key} onClick={() => onPick?.(a.key, a.label)} onMouseEnter={() => setHover(a.i)}
                    className={`w-full flex items-center gap-2 text-xs px-1 py-0.5 rounded ${onPick && a.key ? "hover:bg-muted/60 cursor-pointer" : "cursor-default"}`}>
              <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: a.color }} />
              <span className="truncate font-medium">{a.label}</span>
              <span className="ml-auto tabular-nums text-muted-foreground whitespace-nowrap">{usd(a.value)} · {Math.round((a.value / total) * 100)}%</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="rounded border bg-background overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
          <tr>{head.map((h, i) => <th key={i} className={`px-3 py-2 ${i ? "text-right" : "text-left"}`}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td className="px-3 py-2 text-muted-foreground" colSpan={head.length}>No limit covers this scope yet.</td></tr>}
          {rows.map((r, i) => (
            <tr key={i} className="border-t">
              {r.map((c, j) => <td key={j} className={`px-3 py-1.5 tabular-nums ${j ? "text-right" : "text-left"}`}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
