"use client";

import { useEffect, useState } from "react";

export default function FidelityCostPage() {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
    fetch(`${apiBase}/api/_debug/fidelity-stats`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        setStats(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <main className="p-8 text-sm text-muted-foreground">Loading…</main>;
  if (!stats) return <main className="p-8 text-sm text-destructive">Stats endpoint unreachable.</main>;

  return (
    <main className="bg-background min-h-screen p-8">
      <h1 className="text-2xl font-semibold mb-1">Fidelity Cost Dashboard</h1>
      <p className="text-sm text-muted-foreground mb-6">
        Per-project + per-page costs from `/api/_debug/fidelity-stats`.
      </p>

      <div className="grid grid-cols-4 gap-3 mb-6">
        <Stat label="Projects" value={stats.projects} />
        <Stat label="Pages scored" value={stats.pages_scored} />
        <Stat label="Pass rate" value={`${(stats.pass_rate * 100).toFixed(0)}%`} />
        <Stat label="Avg cost" value={`$${stats.avg_cost_usd?.toFixed(2) ?? "0.00"}`} />
      </div>

      <h2 className="text-sm font-semibold mb-3">Iteration Distribution</h2>
      <div className="grid grid-cols-4 gap-3 mb-6">
        {Object.entries(stats.iter_distribution || {}).map(([iter, count]: [string, any]) => (
          <Stat key={iter} label={`Iter ${iter}`} value={count} />
        ))}
      </div>

      <h2 className="text-sm font-semibold mb-3">Health Signals</h2>
      <ul className="space-y-1 text-xs text-muted-foreground">
        <li>Median score: {stats.median_score}</li>
        <li>Avg iters: {stats.avg_iters}</li>
        <li>Cap exhausted: {stats.cap_exhausted}</li>
      </ul>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="rounded border bg-card p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="text-2xl font-bold mt-1 tabular-nums">{value ?? "—"}</p>
    </div>
  );
}
