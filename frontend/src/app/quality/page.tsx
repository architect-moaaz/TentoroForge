"use client";

/**
 * Quality dashboard (IRF M7-T3) — /quality
 * Reads /api/quality/metrics from the FastAPI backend and renders a
 * single-page snapshot of substrate health. Refresh with the button.
 */
import { useCallback, useEffect, useState } from "react";

type ShapeAvg = { avg_score: number; count: number };

type Metrics = {
  generated_at: string;
  log_dir: string;
  lookback_rows: number;
  row_count: number;
  summary: {
    total_generations: number;
    coverage: {
      in_scope: number;
      extension_needed: number;
      out_of_scope: number;
      unknown: number;
      extension_needed_rate_pct: number;
    };
    guards_fired_top: Array<[string, number]>;
    manual_patches_per_gen_avg: number;
    smith_turn_success_pct: number;
  };
  design_critic_by_shape: Record<string, ShapeAvg>;
};

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:6500";

export default function QualityDashboard() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BACKEND}/api/quality/metrics`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setMetrics(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="min-h-screen bg-white text-slate-900 p-8">
      <div className="max-w-5xl mx-auto space-y-8">
        <header className="flex items-baseline justify-between border-b border-slate-200 pb-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Substrate quality</h1>
            <p className="text-sm text-slate-500 mt-1">
              IRF M7 — coverage verdict, guards fired, critic scores, Smith outcomes.
            </p>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="text-sm px-3 py-1.5 border border-slate-300 rounded hover:bg-slate-50 disabled:opacity-50"
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
        </header>

        {error && (
          <div className="rounded border border-red-300 bg-red-50 text-red-900 p-3 text-sm">
            Failed to load metrics: {error}
          </div>
        )}

        {metrics && (
          <>
            <MetaLine metrics={metrics} />
            <CoverageBlock summary={metrics.summary} />
            <TwoCol>
              <PatchesBlock summary={metrics.summary} />
              <SmithBlock summary={metrics.summary} />
            </TwoCol>
            <GuardsBlock guards={metrics.summary.guards_fired_top} />
            <CriticByShape byShape={metrics.design_critic_by_shape} />
          </>
        )}
      </div>
    </div>
  );
}

function MetaLine({ metrics }: { metrics: Metrics }) {
  return (
    <p className="text-xs text-slate-500">
      Generated {new Date(metrics.generated_at).toLocaleString()} — reading{" "}
      <code className="bg-slate-100 px-1 rounded">{metrics.log_dir}</code>, last{" "}
      {metrics.row_count} of {metrics.lookback_rows} rows.
    </p>
  );
}

function CoverageBlock({ summary }: { summary: Metrics["summary"] }) {
  const c = summary.coverage;
  return (
    <section>
      <SectionTitle>Coverage verdict</SectionTitle>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat label="Total gens" value={summary.total_generations} />
        <Stat label="In-scope" value={c.in_scope} tone="good" />
        <Stat label="Extension needed" value={c.extension_needed} tone="warn" />
        <Stat label="Out of scope" value={c.out_of_scope} tone="mute" />
        <Stat label="Ext-needed rate" value={`${c.extension_needed_rate_pct}%`} tone={c.extension_needed_rate_pct > 20 ? "warn" : "good"} />
      </div>
      <p className="text-xs text-slate-500 mt-2">
        The number to watch: extension-needed rate should trend down as the gap review grows the substrate.
      </p>
    </section>
  );
}

function PatchesBlock({ summary }: { summary: Metrics["summary"] }) {
  const v = summary.manual_patches_per_gen_avg;
  return (
    <div className="border border-slate-200 rounded-lg p-4">
      <div className="text-xs uppercase tracking-wider text-slate-500">Manual patches / gen</div>
      <div className="text-3xl font-semibold mt-1">{v.toFixed(2)}</div>
      <div className="text-xs text-slate-500 mt-1">Post-generation manual fixes averaged per app.</div>
    </div>
  );
}

function SmithBlock({ summary }: { summary: Metrics["summary"] }) {
  const v = summary.smith_turn_success_pct;
  return (
    <div className="border border-slate-200 rounded-lg p-4">
      <div className="text-xs uppercase tracking-wider text-slate-500">Smith turn success</div>
      <div className="text-3xl font-semibold mt-1">{v}%</div>
      <div className="text-xs text-slate-500 mt-1">Mutation turns that landed a working edit in ≤turn-cap.</div>
    </div>
  );
}

function GuardsBlock({ guards }: { guards: Metrics["summary"]["guards_fired_top"] }) {
  if (!guards || guards.length === 0) {
    return (
      <section>
        <SectionTitle>Guards fired (top 10)</SectionTitle>
        <p className="text-sm text-slate-500">No guard data in the window.</p>
      </section>
    );
  }
  const max = Math.max(...guards.map(([, n]) => n));
  return (
    <section>
      <SectionTitle>Guards fired (top 10)</SectionTitle>
      <ul className="space-y-1">
        {guards.map(([name, count]) => (
          <li key={name} className="flex items-center gap-3 text-sm">
            <span className="w-64 truncate font-mono text-xs">{name}</span>
            <span className="flex-1 h-2 bg-slate-100 rounded overflow-hidden">
              <span
                className="block h-full bg-slate-700"
                style={{ width: `${Math.round((count / max) * 100)}%` }}
              />
            </span>
            <span className="w-10 text-right tabular-nums">{count}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CriticByShape({ byShape }: { byShape: Metrics["design_critic_by_shape"] }) {
  const rows = Object.entries(byShape).sort((a, b) => b[1].count - a[1].count);
  if (rows.length === 0) {
    return (
      <section>
        <SectionTitle>Design-critic score by shape</SectionTitle>
        <p className="text-sm text-slate-500">No critic scores logged yet.</p>
      </section>
    );
  }
  return (
    <section>
      <SectionTitle>Design-critic score by shape</SectionTitle>
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-200">
          <tr>
            <th className="py-2">Shape label</th>
            <th className="py-2 text-right">Avg score</th>
            <th className="py-2 text-right">Gens</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, { avg_score, count }]) => (
            <tr key={label} className="border-b border-slate-100">
              <td className="py-2 font-mono text-xs">{label}</td>
              <td className="py-2 text-right tabular-nums">{avg_score}</td>
              <td className="py-2 text-right tabular-nums">{count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function TwoCol({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-1 md:grid-cols-2 gap-3">{children}</div>;
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="text-sm font-semibold tracking-wide uppercase text-slate-700 mb-3">{children}</h2>;
}

function Stat({ label, value, tone = "neutral" }: { label: string; value: number | string; tone?: "good" | "warn" | "mute" | "neutral" }) {
  const toneClass =
    tone === "good"
      ? "border-emerald-200 bg-emerald-50 text-emerald-900"
      : tone === "warn"
        ? "border-amber-200 bg-amber-50 text-amber-900"
        : tone === "mute"
          ? "border-slate-200 bg-slate-50 text-slate-600"
          : "border-slate-200 bg-white text-slate-900";
  return (
    <div className={`border rounded-lg p-3 ${toneClass}`}>
      <div className="text-xs uppercase tracking-wider opacity-70">{label}</div>
      <div className="text-2xl font-semibold mt-1 tabular-nums">{value}</div>
    </div>
  );
}
