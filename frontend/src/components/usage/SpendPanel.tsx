"use client";

/**
 * Spend — who spent what, through which agent, by day / week / month /
 * year; the account's balance against the credit recorded; and the limits
 * an administrator keeps per organisation, person and application.
 *
 * Reads GET /api/spend/report and /api/spend/standing; writes credit with
 * POST /api/spend/credits and limits with PUT /api/spend/limits (admins).
 * A build or a Smith turn that the balance or a limit cannot cover is
 * refused at the door (402) with the same figures shown here.
 */

import { useCallback, useEffect, useState } from "react";
import { useAuthStore } from "@/stores/auth";
import { api } from "@/lib/api";

type Bucket = { cost_usd: number; calls: number; input_tokens: number; output_tokens: number };
type Report = {
  period: string; from: string; to: string;
  total: Bucket;
  by_agent: (Bucket & { agent: string })[];
  by_project: (Bucket & { project: string; name: string })[];
  by_user: (Bucket & { user: string })[];
  by_phase: (Bucket & { phase: string })[];
  by_day: { day: string; cost_usd: number }[];
};
type Standing = {
  balance: { known: boolean; credit_usd: number; spent_usd: number; balance_usd: number | null; since: string | null };
  limits: { scope: string; period: string; spent_usd: number; limit_usd: number | null; left_usd: number | null }[];
  policy: { credits: { at: number; amount: number; note: string; by: string }[]; limits: Record<string, Record<string, number>> };
  build_estimate_usd: number;
};

const PERIODS = ["day", "week", "month", "year"] as const;
type Period = (typeof PERIODS)[number];
const usd = (v: number | null | undefined) =>
  v == null ? "—" : v >= 100 ? `$${v.toFixed(0)}` : v >= 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(3)}`;

export function SpendPanel() {
  const user = useAuthStore((s) => s.user) as { email?: string; orgs?: { org_id: string; role: string; name?: string }[] } | null;
  const isAdmin = !!user?.orgs?.some((o) => o.role === "owner" || o.role === "admin");
  const orgs = user?.orgs ?? [];

  const [period, setPeriod] = useState<Period>("month");
  const [at, setAt] = useState<string>("");
  const [scope, setScope] = useState<string>(isAdmin ? "platform" : "me");
  const [report, setReport] = useState<Report | null>(null);
  const [standing, setStanding] = useState<Standing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [credit, setCredit] = useState({ amount: "", note: "" });
  const [limit, setLimit] = useState({ scope: "platform", day: "", week: "", month: "", year: "" });
  const [saving, setSaving] = useState(false);

  const params = useCallback(() => {
    const p = new URLSearchParams({ period });
    if (at) p.set("at", at);
    if (scope === "me") p.set("person", "me");
    else if (scope.startsWith("org:")) p.set("org", scope.slice(4));
    return p;
  }, [period, at, scope]);

  const load = useCallback(() => {
    setError(null);
    const p = params();
    const s = new URLSearchParams(p);
    s.delete("period"); s.delete("at");
    Promise.all([
      api.get<Report>(`/api/spend/report?${p.toString()}`),
      api.get<Standing>(`/api/spend/standing?${s.toString()}`),
    ])
      .then(([r, st]) => { setReport(r); setStanding(st); })
      .catch((e) => setError(e?.message ?? "Request failed"));
  }, [params]);

  useEffect(() => { load(); }, [load]);

  const addCredit = async () => {
    const amount = Number(credit.amount);
    if (!amount || amount <= 0) return;
    setSaving(true);
    try {
      await api.post("/api/spend/credits", { amount, note: credit.note });
      setCredit({ amount: "", note: "" });
      load();
    } catch (e: any) { setError(e?.message ?? "Could not record the credit"); }
    finally { setSaving(false); }
  };

  const saveLimits = async () => {
    setSaving(true);
    try {
      const body: Record<string, unknown> = { scope: limit.scope };
      for (const k of PERIODS) body[k] = limit[k] === "" ? null : Number(limit[k]);
      await api.put("/api/spend/limits", body);
      load();
    } catch (e: any) { setError(e?.message ?? "Could not save the limits"); }
    finally { setSaving(false); }
  };

  const bal = standing?.balance;

  return (
    <section className="mb-10">
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <div>
          <h2 className="text-lg font-semibold">Spend</h2>
          <p className="text-xs text-muted-foreground">Who spent what, by agent, for the period.</p>
        </div>
        <div className="ml-auto flex flex-wrap gap-2 items-center">
          <select className="rounded border bg-background px-2 py-1 text-sm" value={scope}
                  onChange={(e) => setScope(e.target.value)}>
            {isAdmin && <option value="platform">Whole platform</option>}
            <option value="me">Me ({user?.email ?? "me"})</option>
            {isAdmin && orgs.map((o) => (
              <option key={o.org_id} value={`org:${o.org_id}`}>Organisation {o.name ?? o.org_id.slice(0, 8)}</option>
            ))}
          </select>
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

      {error && <p className="text-sm text-destructive mb-3">{error}</p>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Kpi label={`Spent this ${period}`} value={usd(report?.total.cost_usd)} sub={report ? `${report.total.calls} calls` : ""} />
        <Kpi label="Account balance" value={bal?.known ? usd(bal.balance_usd) : "not recorded"}
             sub={bal?.known ? `${usd(bal.credit_usd)} credited · ${usd(bal.spent_usd)} spent since ${bal.since?.slice(0, 10)}` : "record the opening balance below"} />
        <Kpi label="A build is expected to cost" value={usd(standing?.build_estimate_usd)} sub="median of this month's builds" />
        <Kpi label="Tokens" value={report ? `${Math.round((report.total.input_tokens + report.total.output_tokens) / 1000)}k` : "—"}
             sub={report ? `${Math.round(report.total.input_tokens / 1000)}k in · ${Math.round(report.total.output_tokens / 1000)}k out` : ""} />
      </div>

      <div className="grid md:grid-cols-2 gap-6 mb-6">
        <Table title="By agent" rows={(report?.by_agent ?? []).map((r) => [r.agent, r.calls, usd(r.cost_usd)])} head={["Agent", "Calls", "Cost"]} />
        <Table title="By person" rows={(report?.by_user ?? []).map((r) => [r.user || "unattributed", r.calls, usd(r.cost_usd)])} head={["Person", "Calls", "Cost"]} />
        <Table title="By application" rows={(report?.by_project ?? []).map((r) => [r.name ? `${r.name} (${r.project})` : r.project, r.calls, usd(r.cost_usd)])} head={["Application", "Calls", "Cost"]} />
        <Table title="By day" rows={(report?.by_day ?? []).map((r) => [r.day, "", usd(r.cost_usd)])} head={["Day", "", "Cost"]} />
      </div>

      {standing && (
        <div className="mb-6">
          <h3 className="text-sm font-semibold mb-2">Limits that cover this scope</h3>
          <Table head={["Scope", "Period", "Spent", "Limit", "Left"]}
                 rows={standing.limits.filter((l) => l.limit_usd != null || l.spent_usd > 0).map((l) => [
                   l.scope === "platform" ? "Whole platform" : l.scope, l.period, usd(l.spent_usd),
                   l.limit_usd == null ? "none" : usd(l.limit_usd), l.left_usd == null ? "—" : usd(l.left_usd)])} />
        </div>
      )}

      {isAdmin && (
        <div className="grid md:grid-cols-2 gap-6">
          <div className="rounded border bg-card p-4">
            <h3 className="text-sm font-semibold mb-1">Record credit</h3>
            <p className="text-xs text-muted-foreground mb-3">The first entry is the opening balance; then every top-up. The balance above is credit minus everything spent since.</p>
            <div className="flex gap-2">
              <input className="w-28 rounded border bg-background px-2 py-1 text-sm" placeholder="Amount $" inputMode="decimal"
                     value={credit.amount} onChange={(e) => setCredit({ ...credit, amount: e.target.value })} />
              <input className="flex-1 rounded border bg-background px-2 py-1 text-sm" placeholder="Note (top-up, opening balance…)"
                     value={credit.note} onChange={(e) => setCredit({ ...credit, note: e.target.value })} />
              <button onClick={addCredit} disabled={saving} className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50">Add</button>
            </div>
            {standing?.policy.credits.length ? (
              <ul className="mt-3 text-xs text-muted-foreground space-y-0.5">
                {standing.policy.credits.slice(-5).reverse().map((c, i) => (
                  <li key={i}>{new Date(c.at * 1000).toISOString().slice(0, 10)} · {usd(c.amount)} · {c.note || "credit"} · {c.by}</li>
                ))}
              </ul>
            ) : null}
          </div>
          <div className="rounded border bg-card p-4">
            <h3 className="text-sm font-semibold mb-1">Spending limits</h3>
            <p className="text-xs text-muted-foreground mb-3">Per scope and period. A build or a turn that would cross one is not started. Leave a period empty for no limit.</p>
            <select className="w-full rounded border bg-background px-2 py-1 text-sm mb-2" value={limit.scope}
                    onChange={(e) => setLimit({ ...limit, scope: e.target.value })}>
              <option value="platform">Whole platform</option>
              {orgs.map((o) => <option key={o.org_id} value={`org:${o.org_id}`}>Organisation {o.name ?? o.org_id.slice(0, 8)}</option>)}
              {user?.email && <option value={`user:${user.email}`}>Person {user.email}</option>}
              {(report?.by_user ?? []).filter((r) => r.user && r.user !== user?.email).map((r) => (
                <option key={r.user} value={`user:${r.user}`}>Person {r.user}</option>))}
              {(report?.by_project ?? []).map((r) => (
                <option key={r.project} value={`project:${r.project}`}>Application {r.name || r.project}</option>))}
            </select>
            <div className="grid grid-cols-4 gap-2">
              {PERIODS.map((p) => (
                <label key={p} className="text-xs text-muted-foreground capitalize">{p}
                  <input className="mt-1 w-full rounded border bg-background px-2 py-1 text-sm" placeholder="$" inputMode="decimal"
                         value={limit[p]} onChange={(e) => setLimit({ ...limit, [p]: e.target.value })} />
                </label>
              ))}
            </div>
            <button onClick={saveLimits} disabled={saving} className="mt-3 rounded bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50">Save limits</button>
          </div>
        </div>
      )}
    </section>
  );
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

function Table({ title, head, rows }: { title?: string; head: string[]; rows: (string | number)[][] }) {
  return (
    <div>
      {title && <h3 className="text-sm font-semibold mb-2">{title}</h3>}
      <div className="rounded border bg-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr>{head.map((h, i) => <th key={i} className={`px-3 py-2 ${i ? "text-right" : "text-left"}`}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td className="px-3 py-2 text-muted-foreground" colSpan={head.length}>Nothing in this period.</td></tr>}
            {rows.map((r, i) => (
              <tr key={i} className="border-t">
                {r.map((c, j) => <td key={j} className={`px-3 py-1.5 tabular-nums ${j ? "text-right" : "text-left"}`}>{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
