"use client";

/**
 * Ambiguity-ledger chip card — REL-S1-T3.
 *
 * Renders the pipeline's pending picks (below high-confidence) so the
 * user can confirm or swap. Confirmations write to bindings.json via
 * `POST /api/projects/{id}/open-decisions/confirm` (id in the body); the
 * next regen's emitter reads bindings and short-circuits with the
 * confirmed target (see `orphan_wiring_pass._dl.resolve_binding`).
 *
 * High-confidence picks stay silent — they're recorded in the ledger
 * for auditing but never surface as chips. Only medium/low picks
 * (unresolved candidates, close runner-ups) get user attention.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Check, ChevronDown, HelpCircle } from "lucide-react";
import { api, ApiError } from "@/lib/api";

// ── Shape mirrors backend services.decision_ledger.Decision ────────

interface Alternative {
  target: string;
  score?: number;
  reason?: string;
}

interface Decision {
  decision_id: string;
  kind: string;        // "button_target" | "form_submit" | "fk_target" | "archetype"
  scope: string;
  identity: string;
  target_picked: string;
  confidence: "high" | "medium" | "low";
  source_emitter: string;
  alternatives?: Alternative[];
  reason?: string;
  resolved?: boolean;
  resolved_target?: string;
}

interface LedgerResponse {
  decisions: Decision[];
  pending_count: number;
}

// ── Presentation helpers ────────────────────────────────────────────

const KIND_LABEL: Record<string, string> = {
  button_target: "Button → workflow",
  form_submit:   "Form → submit",
  fk_target:     "Foreign key",
  archetype:     "App archetype",
};

function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind.replace(/_/g, " ");
}

// Strip conventional prefixes so the chip reads as prose:
//   "page:/documents/upload" → "/documents/upload"
//   "workflow:UploadDocs" → "UploadDocs"
function displayTarget(t: string): string {
  const colon = t.indexOf(":");
  return colon > 0 && colon < 20 ? t.slice(colon + 1) : t;
}

function bandTint(band: string): string {
  if (band === "low") return "border-amber-500/40 bg-amber-50 dark:bg-amber-950/20";
  if (band === "medium") return "border-blue-500/40 bg-blue-50 dark:bg-blue-950/20";
  return "border-emerald-500/40 bg-emerald-50 dark:bg-emerald-950/20";
}

function bandIcon(band: string) {
  if (band === "low") return <AlertCircle className="h-3.5 w-3.5 text-amber-600" />;
  return <HelpCircle className="h-3.5 w-3.5 text-blue-600" />;
}


interface Props {
  projectId: string;
  /** Optional: caller can supply a fetched ledger to skip the initial GET
   * (e.g. when a generation-complete SSE already carried it). */
  initial?: LedgerResponse;
}

export function OpenDecisionsCard({ projectId, initial }: Props) {
  const [data, setData] = useState<LedgerResponse | null>(initial ?? null);
  const [loading, setLoading] = useState(!initial);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  // Collapsed by default. This card sits ABOVE the chat history, and a
  // real app produces dozens of below-confidence picks (23 on the
  // Legislative Council build) — rendering them all pushed the Smith
  // chat completely off screen with no way to get back to it. The
  // decisions are advisory; the chat is the primary surface.
  const [listOpen, setListOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<LedgerResponse>(
        `/api/projects/${projectId}/open-decisions`,
      );
      setData(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load decisions");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (!initial) void load();
  }, [initial, load]);

  const confirm = useCallback(async (decision_id: string, target: string) => {
    setSavingId(decision_id);
    setError(null);
    try {
      // The id goes in the BODY. Decision ids embed app routes
      // (`file-documents/new-json`), and a percent-encoded slash is decoded
      // back to `/` before routing — so a path-param id 404'd with a bare
      // "Not Found" for every nested-route decision.
      await api.post(
        `/api/projects/${projectId}/open-decisions/confirm`,
        { decision_id, target },
      );
      // Optimistically mark resolved so the row disappears; refetch to
      // sync the pending_count badge with the server view.
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          decisions: prev.decisions.map((d) =>
            d.decision_id === decision_id
              ? { ...d, resolved: true, resolved_target: target }
              : d,
          ),
          pending_count: Math.max(0, prev.pending_count - 1),
        };
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to confirm decision");
    } finally {
      setSavingId(null);
    }
  }, [projectId]);

  // Only surface unresolved medium/low picks — high-confidence ships silently
  const pending = useMemo(() => {
    if (!data) return [];
    return data.decisions.filter(
      (d) => !d.resolved && (d.confidence === "medium" || d.confidence === "low"),
    );
  }, [data]);

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-background p-3 text-[13px] text-muted-foreground">
        Loading decisions…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-[13px] text-destructive">
        {error}
      </div>
    );
  }
  if (!pending.length) {
    // Silent good state — nothing pending. Rendering nothing keeps the
    // project page uncluttered when the pipeline nailed every pick.
    return null;
  }

  return (
    <div className="rounded-lg border border-border bg-background p-3 text-[13px]">
      {/* The whole header is the toggle — one click gets the chat back. */}
      <button
        type="button"
        onClick={() => setListOpen((v) => !v)}
        aria-expanded={listOpen}
        className="flex w-full items-center justify-between gap-2 text-left"
      >
        <div className="flex items-center gap-2 text-muted-foreground">
          <HelpCircle className="h-4 w-4 shrink-0" />
          <span className="font-medium text-foreground">
            {pending.length} decision{pending.length === 1 ? "" : "s"} to confirm
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden sm:inline text-[11px] text-muted-foreground">
            {listOpen
              ? "Confirm or swap each pick."
              : "Pipeline wasn't certain — review when you're ready."}
          </span>
          <ChevronDown
            className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${
              listOpen ? "rotate-180" : ""
            }`}
          />
        </div>
      </button>

      {/* Capped height: even expanded, the list never takes the whole panel,
          so the chat below stays reachable without collapsing again. */}
      <div
        className={`mt-2 flex flex-col gap-2 overflow-y-auto ${
          listOpen ? "max-h-72" : "hidden"
        }`}
      >
        {pending.map((d) => {
          const isExpanded = expandedId === d.decision_id;
          const isSaving = savingId === d.decision_id;
          const alts = d.alternatives ?? [];
          return (
            <div
              key={d.decision_id}
              className={`rounded-md border p-2.5 ${bandTint(d.confidence)}`}
            >
              <div className="flex items-start gap-2">
                {bandIcon(d.confidence)}
                <div className="flex-1 min-w-0">
                  <div className="text-[11px] text-muted-foreground uppercase tracking-wide">
                    {kindLabel(d.kind)}
                    <span className="mx-1">·</span>
                    <span className="lowercase font-normal">
                      {displayTarget(d.scope)}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[13px] font-medium text-foreground break-words">
                    {d.identity}
                    <span className="mx-1.5 text-muted-foreground">→</span>
                    <span>{displayTarget(d.target_picked)}</span>
                  </div>
                  {d.reason && (
                    <div className="mt-1 text-[11px] text-muted-foreground line-clamp-2">
                      {d.reason}
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  disabled={isSaving}
                  onClick={() => confirm(d.decision_id, d.target_picked)}
                  className="inline-flex items-center gap-1 rounded-md bg-foreground px-2.5 py-1 text-[11px] font-medium text-background hover:opacity-90 disabled:opacity-50"
                >
                  <Check className="h-3 w-3" />
                  Confirm pick
                </button>
                {alts.length > 0 && (
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedId(isExpanded ? null : d.decision_id)
                    }
                    className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[11px] font-medium text-foreground hover:bg-accent hover:text-accent-foreground"
                  >
                    <ChevronDown
                      className={`h-3 w-3 transition-transform ${
                        isExpanded ? "rotate-180" : ""
                      }`}
                    />
                    {alts.length} alternative{alts.length === 1 ? "" : "s"}
                  </button>
                )}
              </div>

              {isExpanded && alts.length > 0 && (
                <div className="mt-2 flex flex-col gap-1 pt-1.5 border-t border-border/60">
                  {alts.map((a) => (
                    <button
                      key={a.target}
                      type="button"
                      disabled={isSaving}
                      onClick={() => confirm(d.decision_id, a.target)}
                      className="flex flex-col items-start gap-0.5 rounded-md border border-border/60 bg-background/80 px-2.5 py-1.5 text-left hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <span className="text-[12px] font-medium">
                        Swap → {displayTarget(a.target)}
                      </span>
                      {typeof a.score === "number" && a.score > 0 && (
                        <span className="text-[10px] text-muted-foreground">
                          score {a.score.toFixed(2)}
                          {a.reason && <span> · {a.reason}</span>}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
