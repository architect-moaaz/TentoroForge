"use client";

/**
 * RemediationReport — SV-10
 *
 * Detailed panel behind a SelfVerifyCard click. Shows every fault
 * grouped by priority, expandable evidence (network log, console,
 * stack trace, screenshot).
 *
 * Backed by GET /api/projects/{project_id}/verify/{run_id} which
 * returns the raw runner report as `report.faults[]` + the classified
 * RemediationReport JSON as `remediation`.
 */
import { AlertTriangle, XCircle, Info, ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

interface RawFault {
  interaction_id: string;
  interaction: {
    kind: string;
    route?: string;
    label?: string;
    dataSource?: string;
    param_name?: string;
    entity?: string | null;
    action?: { kind: string; workflow_target?: string; navigate_target?: string };
    submit?: { kind: string; workflow_target?: string; dataSource_target?: string };
  };
  evidence: {
    status?: number | null;
    stack_trace?: string | null;
    body_excerpt?: string | null;
    network_log?: Array<{ method: string; url: string; status: number }>;
    console?: Array<{ level: string; text: string }>;
    rows_returned?: number | null;
    timed_out?: boolean;
    url_after_click?: string | null;
  };
}

interface RunReport {
  id: string;
  status: string;
  target: string;
  interactions_run: number | null;
  interactions_passed: number | null;
  faults_count: number | null;
  rounds_run: number | null;
  report?: { faults?: RawFault[] };
  remediation?: {
    rounds_run?: number;
    fixed?: string[];
    escalated?: Array<{ id?: string; signature?: string; reason?: string; error?: string }>;
    final_fault_count?: number;
  } | null;
}

interface Props {
  projectId: string;
  runId: string;
}

export function RemediationReport({ projectId, runId }: Props) {
  const [run, setRun] = useState<RunReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [openFaultId, setOpenFaultId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetch(`/api/projects/${projectId}/verify/${runId}`, {
      credentials: "include",
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j) => { if (alive) setRun(j); })
      .catch((e) => { if (alive) setErr(String(e)); });
    return () => { alive = false; };
  }, [projectId, runId]);

  if (err) return <div className="text-sm text-red-700">Couldn't load report: {err}</div>;
  if (!run) return <div className="text-sm text-neutral-500">Loading verification report…</div>;

  const faults = run.report?.faults ?? [];
  const remediation = run.remediation ?? undefined;

  return (
    <div className="space-y-3 text-sm">
      <header className="flex items-baseline gap-4 border-b pb-2">
        <span className="font-semibold">Self-Verify Report</span>
        <span className="text-neutral-500">
          {run.interactions_passed ?? 0}/{run.interactions_run ?? 0} passed
          {" · "}{run.faults_count ?? 0} faults
          {run.rounds_run ? ` · ${run.rounds_run} round${run.rounds_run > 1 ? "s" : ""}` : ""}
          {" · target: "}{run.target}
        </span>
      </header>

      {remediation && (
        <div className="rounded border border-emerald-200 bg-emerald-50 p-2 text-emerald-800">
          Smith rounds: {remediation.rounds_run ?? 0} · fixed: {remediation.fixed?.length ?? 0} · escalated: {remediation.escalated?.length ?? 0}
        </div>
      )}

      {faults.length === 0 ? (
        <div className="rounded border border-emerald-200 bg-emerald-50 p-3 text-emerald-800">
          No faults — the app is green.
        </div>
      ) : (
        <ul className="space-y-2">
          {faults.map((f, idx) => (
            <li key={f.interaction_id + "-" + idx} className="rounded border border-neutral-200">
              <button
                className="flex w-full items-start justify-between gap-3 p-2 text-left hover:bg-neutral-50"
                onClick={() => setOpenFaultId((cur) => (cur === f.interaction_id ? null : f.interaction_id))}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 font-medium">
                    <FaultIcon kind={f.interaction.kind} />
                    <span className="truncate">
                      {f.interaction.kind}
                      {f.interaction.route ? ` · ${f.interaction.route}` : ""}
                      {f.interaction.label ? ` · ${f.interaction.label}` : ""}
                    </span>
                  </div>
                  <div className="mt-0.5 truncate text-xs text-neutral-500">
                    {_evidenceLine(f)}
                  </div>
                </div>
                {openFaultId === f.interaction_id
                  ? <ChevronDown size={14} className="mt-1 text-neutral-400" />
                  : <ChevronRight size={14} className="mt-1 text-neutral-400" />}
              </button>
              {openFaultId === f.interaction_id && (
                <FaultDetail fault={f} />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


function FaultIcon({ kind }: { kind: string }) {
  if (kind === "route") return <XCircle size={14} className="text-red-600" />;
  if (kind === "list" || kind === "detail") return <Info size={14} className="text-orange-600" />;
  return <AlertTriangle size={14} className="text-amber-600" />;
}


function _evidenceLine(f: RawFault): string {
  const ev = f.evidence;
  const bits: string[] = [];
  if (ev.status != null) bits.push(`HTTP ${ev.status}`);
  if (ev.timed_out) bits.push("timed out");
  if (ev.rows_returned != null) bits.push(`rows=${ev.rows_returned}`);
  if (ev.stack_trace) bits.push(ev.stack_trace.slice(0, 100));
  return bits.join(" · ") || "no evidence";
}


function FaultDetail({ fault }: { fault: RawFault }) {
  const ev = fault.evidence;
  return (
    <div className="space-y-2 border-t border-neutral-100 bg-neutral-50 p-2 text-xs">
      {ev.stack_trace && (
        <details open>
          <summary className="cursor-pointer text-neutral-700">Stack</summary>
          <pre className="mt-1 whitespace-pre-wrap break-all rounded bg-white p-2 font-mono text-[11px]">
            {ev.stack_trace}
          </pre>
        </details>
      )}
      {ev.network_log && ev.network_log.length > 0 && (
        <details>
          <summary className="cursor-pointer text-neutral-700">
            Network ({ev.network_log.length})
          </summary>
          <ul className="mt-1 space-y-0.5 font-mono text-[11px]">
            {ev.network_log.map((n, i) => (
              <li key={i} className={n.status >= 400 ? "text-red-700" : "text-neutral-700"}>
                {n.method} {n.status} {n.url}
              </li>
            ))}
          </ul>
        </details>
      )}
      {ev.console && ev.console.length > 0 && (
        <details>
          <summary className="cursor-pointer text-neutral-700">
            Console ({ev.console.length})
          </summary>
          <ul className="mt-1 space-y-0.5 font-mono text-[11px]">
            {ev.console.map((c, i) => (
              <li key={i} className={c.level === "error" ? "text-red-700" : "text-neutral-700"}>
                [{c.level}] {c.text.slice(0, 200)}
              </li>
            ))}
          </ul>
        </details>
      )}
      {ev.body_excerpt && (
        <details>
          <summary className="cursor-pointer text-neutral-700">Body excerpt</summary>
          <pre className="mt-1 whitespace-pre-wrap break-all rounded bg-white p-2 font-mono text-[11px]">
            {ev.body_excerpt}
          </pre>
        </details>
      )}
    </div>
  );
}
