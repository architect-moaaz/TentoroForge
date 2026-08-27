"use client";

/**
 * VerifyResultCard — JV-27
 *
 * Rich completion card for a Self-Verify Pass. Replaces the plaintext
 * SMITH_VERIFY_COMPLETE bubble. Rendered by ChatMessage when
 * `metadata.verify` is present (message_type is still `chat` on the wire —
 * see backend note in routers/generate.py for why).
 *
 * States drive on `interactions.passed/run`, `faults`, and `status`:
 *   • empty (0 faults, run>0)      → single-line green "Verified · all passed"
 *   • done, faults > 0             → amber header + collapsible faults list
 *   • failed                       → red header + error message
 *   • interaction_pass.skipped     → amber banner explaining the runner
 *                                     sidecar was unavailable (dev boxes)
 *
 * Faults are grouped by interaction-id prefix (form:/nav:/button:/…) if
 * the ids follow that convention; otherwise they render flat.
 */
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Wrench,
} from "lucide-react";
import { useState } from "react";

// Payload shape produced by backend's format_verify_report_json() +
// the JV-27/B1 patches in routers/generate.py._run_verify_then_summarize.
export interface VerifyPayload {
  run_id?: string;
  status?: string | null;
  error?: string | null;
  target?: string;
  invoked_by?: string;
  duration_ms?: number;
  interaction_pass?: { skipped?: boolean; reason?: string } | null;
  interactions?: {
    run?: number | null;
    passed?: number | null;
    faults_count?: number | null;
    rounds_run?: number | null;
  };
  faults?: Array<{
    passed?: boolean;
    flaky?: boolean;
    interaction?: { id?: string; route?: string; label?: string | null };
    evidence?: {
      status?: number | null;
      stack_trace?: string | null;
      body_excerpt?: string | null;
      screenshot_uri?: string | null;
      url_after_click?: string | null;
      playwright_trace_url?: string | null;
    };
    signature?: string;
    classification?: string;
  }>;
  faults_has_more?: boolean;
  journey?: {
    first_run?: { summary?: { passed?: number; total?: number; failed?: number } | null } | null;
    second_run?: { summary?: { passed?: number; total?: number; failed?: number } | null } | null;
  } | null;
}

interface Props {
  verify: VerifyPayload;
  runId?: string;
  onSend?: (msg: string) => void;
}

export function VerifyResultCard({ verify, runId, onSend }: Props) {
  const [expanded, setExpanded] = useState(false);
  const interactions = verify.interactions || {};
  const run = interactions.run ?? 0;
  const passed = interactions.passed ?? 0;
  const faultsCount = interactions.faults_count ?? (verify.faults?.length ?? 0);
  const status = verify.status || "done";
  const skipped = !!verify.interaction_pass?.skipped;
  const duration = _fmtDuration(verify.duration_ms);
  const target = verify.target || "preview";
  const invokedBy = verify.invoked_by || "user_chat";

  // Compact green summary when everything passed and nothing was skipped.
  const isClean =
    status !== "failed" && faultsCount === 0 && !skipped && run > 0;

  if (isClean) {
    return (
      <div className="my-2 inline-flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-800">
        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
        <span>
          Verified · {passed}/{run} interactions passed
          {duration ? ` · ${duration}` : ""}
        </span>
      </div>
    );
  }

  const theme = _themeFor(status, faultsCount);
  const Icon = theme.Icon;
  const faults = verify.faults || [];
  const grouped = _groupFaults(faults);
  const journey = verify.journey || null;
  const journeyFirst = journey?.first_run?.summary;
  const journeySecond = journey?.second_run?.summary;

  return (
    <div className="my-2 rounded-lg border bg-card shadow-sm">
      {/* Header */}
      <div className={`border-b ${theme.headerBg} px-4 py-3`}>
        <div className="flex items-center gap-2">
          <Icon className={`h-4 w-4 ${theme.iconClass}`} />
          <h3 className={`font-semibold text-sm ${theme.headerText}`}>
            {theme.title}
          </h3>
          <span className={`ml-auto text-[10px] ${theme.headerText} opacity-70`}>
            {run > 0 ? `${passed}/${run} passed` : "no interactions run"}
            {faultsCount > 0 ? ` · ${faultsCount} fault${faultsCount === 1 ? "" : "s"}` : ""}
          </span>
        </div>
        <p className={`mt-1 text-[10px] ${theme.headerText} opacity-70`}>
          target={target} · invoked_by={invokedBy}
          {duration ? ` · ${duration}` : ""}
          {runId ? ` · run ${runId.slice(0, 8)}` : ""}
        </p>
      </div>

      <div className="divide-y text-xs">
        {/* Skipped-runner banner */}
        {skipped && (
          <div className="px-4 py-2.5 bg-amber-50/60">
            <div className="flex items-start gap-1.5 text-amber-900">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-amber-600" />
              <span>
                Interaction pass skipped
                {verify.interaction_pass?.reason
                  ? ` — ${verify.interaction_pass.reason}`
                  : " (runner sidecar unavailable)"}
                . Journey walk still ran below.
              </span>
            </div>
          </div>
        )}

        {/* Journey summary mini-bar */}
        {(journeyFirst || journeySecond) && (
          <div className="px-4 py-2.5">
            <div className="mb-1 font-medium text-muted-foreground">Journey walk</div>
            {journeyFirst && (
              <div className="text-muted-foreground">
                First run:{" "}
                <span className={journeyFirst.failed ? "text-amber-700" : "text-emerald-700"}>
                  {journeyFirst.passed ?? 0}/{journeyFirst.total ?? 0} passed
                  {journeyFirst.failed ? ` · ${journeyFirst.failed} failed` : ""}
                </span>
              </div>
            )}
            {journeySecond && (
              <div className="text-muted-foreground">
                After auto-fix:{" "}
                <span className={journeySecond.failed ? "text-amber-700" : "text-emerald-700"}>
                  {journeySecond.passed ?? 0}/{journeySecond.total ?? 0} passed
                  {journeySecond.failed ? ` · ${journeySecond.failed} failed` : " · clean"}
                </span>
              </div>
            )}
          </div>
        )}

        {/* Failed status detail */}
        {status === "failed" && verify.error && (
          <div className="px-4 py-2.5 bg-red-50/40 text-red-900">
            <div className="mb-0.5 font-medium">Run failed</div>
            <div className="text-red-800/80 break-words">{verify.error}</div>
          </div>
        )}

        {/* Faults (collapsible) */}
        {faults.length > 0 && (
          <div className="px-4 py-2.5">
            <button
              className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground hover:text-foreground"
              onClick={() => setExpanded((x) => !x)}
              aria-expanded={expanded}
            >
              {expanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              Faults ({faults.length}
              {verify.faults_has_more ? "+" : ""})
            </button>
            {expanded && (
              <div className="space-y-3">
                {grouped.map(([group, rows]) => (
                  <div key={group}>
                    {grouped.length > 1 && (
                      <div className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                        {group}
                      </div>
                    )}
                    <ul className="space-y-1.5">
                      {rows.map((f, i) => (
                        <li key={i} className="rounded border bg-muted/30 px-2.5 py-1.5">
                          <div className="flex items-start gap-1.5">
                            <code className="rounded bg-background px-1.5 py-0.5 text-[10px] break-all">
                              {f.interaction?.id || f.interaction?.route || "?"}
                            </code>
                            <span className={`ml-auto shrink-0 rounded px-1.5 py-0.5 text-[10px] ${_pillFor(_classifyOf(f))}`}>
                              {_classifyOf(f)}
                            </span>
                          </div>
                          <p className="mt-1 text-[11px] text-muted-foreground break-words">
                            {_excerptOf(f)}
                          </p>
                          <div className="mt-1 flex gap-2">
                            {f.evidence?.playwright_trace_url && (
                              <a
                                href={f.evidence.playwright_trace_url}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-[10px] text-blue-700 hover:underline"
                              >
                                <ExternalLink className="h-2.5 w-2.5" />
                                Trace
                              </a>
                            )}
                            {f.evidence?.screenshot_uri && (
                              <a
                                href={f.evidence.screenshot_uri}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-[10px] text-blue-700 hover:underline"
                              >
                                <ExternalLink className="h-2.5 w-2.5" />
                                Screenshot
                              </a>
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Footer action */}
        {faults.length > 0 && onSend && (
          <div className="px-4 py-2.5">
            <button
              onClick={() =>
                onSend("Fix the faults from the last verify run")
              }
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90"
            >
              <Wrench className="h-3 w-3" />
              Fix these
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── helpers ────────────────────────────────────────────────────────────

function _themeFor(status: string, faults: number) {
  if (status === "failed") {
    return {
      headerBg: "bg-gradient-to-r from-red-50 to-rose-50",
      headerText: "text-red-900",
      iconClass: "text-red-600",
      Icon: XCircle,
      title: "Self-Verify failed",
    };
  }
  if (faults > 0) {
    return {
      headerBg: "bg-gradient-to-r from-amber-50 to-yellow-50",
      headerText: "text-amber-900",
      iconClass: "text-amber-600",
      Icon: AlertTriangle,
      title: "Self-Verify · faults found",
    };
  }
  return {
    headerBg: "bg-gradient-to-r from-emerald-50 to-green-50",
    headerText: "text-emerald-900",
    iconClass: "text-emerald-600",
    Icon: CheckCircle2,
    title: "Self-Verify complete",
  };
}

function _fmtDuration(ms?: number): string {
  if (!ms || ms < 0) return "";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem ? `${m}m ${rem}s` : `${m}m`;
}

function _classifyOf(f: VerifyPayload["faults"] extends (infer R)[] | undefined ? R : never): string {
  const explicit = f?.signature || f?.classification;
  if (explicit) return explicit;
  const stack = (f?.evidence?.stack_trace || "").toLowerCase();
  if (!stack) return "unclassified";
  if (stack.includes("err_name_not_resolved") || stack.includes("dns")) return "network-error";
  if (stack.includes("err_connection_refused") || stack.includes("econnrefused")) return "network-error";
  if (stack.includes("timeout") || stack.includes("timed out")) return "timeout";
  if (stack.split("\n", 1)[0].includes("500")) return "server-error";
  return "runtime";
}

function _excerptOf(f: VerifyPayload["faults"] extends (infer R)[] | undefined ? R : never): string {
  const stack = f?.evidence?.stack_trace || "";
  if (stack) return stack.split("\n", 1)[0].trim().slice(0, 200);
  const body = f?.evidence?.body_excerpt || "";
  if (body) return body.slice(0, 200);
  return "(no evidence captured)";
}

function _pillFor(kind: string): string {
  switch (kind) {
    case "network-error":
      return "bg-blue-100 text-blue-800";
    case "timeout":
      return "bg-amber-100 text-amber-800";
    case "server-error":
      return "bg-red-100 text-red-800";
    case "runtime":
      return "bg-purple-100 text-purple-800";
    case "unclassified":
      return "bg-muted text-muted-foreground";
    default:
      return "bg-slate-100 text-slate-800";
  }
}

type FaultRow = NonNullable<VerifyPayload["faults"]>[number];

function _groupFaults(faults: FaultRow[]): Array<[string, FaultRow[]]> {
  const groups: Record<string, FaultRow[]> = {};
  for (const f of faults) {
    const id = f.interaction?.id || "";
    const prefix = id.includes(":") ? id.split(":", 1)[0] : "other";
    (groups[prefix] ||= []).push(f);
  }
  return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
}
