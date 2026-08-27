"use client";

/**
 * Dev-only verify-history view.
 *
 * Reads the existing GET /api/projects/{id}/verify endpoint and shows a
 * simple table of recent runs. Meant for operators to sanity-check
 * retention (JV-11) and click through to individual run detail via the
 * per-run GET endpoint.
 *
 * Rendered under /dev/verify-history/<projectId> — no auth/session
 * wiring beyond what the browser already sent. If unauthenticated, the
 * backend 401s and the list stays empty.
 */
import { useEffect, useState } from "react";
import { use } from "react";

interface VerifyRunRow {
  id: string;
  status: string;
  invoked_by: string;
  target: string;
  interactions_run: number | null;
  interactions_passed: number | null;
  faults_count: number | null;
  rounds_run: number | null;
  created_at: string;
  completed_at: string | null;
  error: string | null;
}

export default function VerifyHistoryPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  // Next.js 15+ params are promises — unwrap with React.use().
  const { projectId } = use(params);
  const [rows, setRows] = useState<VerifyRunRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch(`/api/projects/${projectId}/verify`, {
      credentials: "include",
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(`GET failed: ${r.status}`);
        return r.json();
      })
      .then((data) => alive && setRows(data as VerifyRunRow[]))
      .catch((e) => alive && setErr(String(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [projectId]);

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-4 text-sm">
      <h1 className="text-lg font-semibold">Verify history</h1>
      <div className="text-xs text-muted-foreground">
        project <code>{projectId}</code> · limited to the last{" "}
        {process.env.NEXT_PUBLIC_FORGE_VERIFY_RETENTION ?? "20"} runs (server retention).
      </div>

      {loading && <div>Loading…</div>}
      {err && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-red-800">
          {err}
        </div>
      )}
      {!loading && !err && rows.length === 0 && (
        <div className="rounded border p-3 text-muted-foreground">
          No verify runs yet. Trigger one from the completion card or by
          typing &ldquo;verify the app&rdquo; in chat.
        </div>
      )}

      {rows.length > 0 && (
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-b bg-muted/40 text-left">
              <th className="p-2">Started</th>
              <th className="p-2">Status</th>
              <th className="p-2">Trigger</th>
              <th className="p-2">Target</th>
              <th className="p-2">Passed / Total</th>
              <th className="p-2">Faults</th>
              <th className="p-2">Rounds</th>
              <th className="p-2">Duration</th>
              <th className="p-2"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const dur =
                r.completed_at && r.created_at
                  ? Math.round(
                      (Date.parse(r.completed_at) -
                        Date.parse(r.created_at)) /
                        1000,
                    )
                  : null;
              return (
                <tr key={r.id} className="border-b hover:bg-muted/20">
                  <td className="p-2 font-mono text-[10px]">
                    {r.created_at.slice(0, 19).replace("T", " ")}
                  </td>
                  <td className="p-2">
                    <StatusPill status={r.status} />
                  </td>
                  <td className="p-2">{r.invoked_by}</td>
                  <td className="p-2">{r.target}</td>
                  <td className="p-2">
                    {r.interactions_passed ?? "—"} / {r.interactions_run ?? "—"}
                  </td>
                  <td className="p-2">{r.faults_count ?? "—"}</td>
                  <td className="p-2">{r.rounds_run ?? "—"}</td>
                  <td className="p-2">{dur !== null ? `${dur}s` : "—"}</td>
                  <td className="p-2">
                    <a
                      href={`/api/projects/${projectId}/verify/${r.id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-blue-600 hover:underline"
                    >
                      JSON
                    </a>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const colors: Record<string, string> = {
    running: "bg-amber-100 text-amber-800",
    done: "bg-emerald-100 text-emerald-800",
    failed: "bg-red-100 text-red-800",
    pending: "bg-slate-100 text-slate-700",
  };
  const cls = colors[status] ?? "bg-slate-100 text-slate-700";
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] ${cls}`}>
      {status}
    </span>
  );
}
