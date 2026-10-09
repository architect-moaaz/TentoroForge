"use client";

// The Huddle Room's record in Smith's panel: each time the agents that own the
// parts of a question met — who, what each said, what the observer decided,
// what came of it — and the person's way to decide otherwise.
//
// The agents decide and carry it out without waiting; the person watches and
// may overrule afterwards. An overrule is recorded first (the decision becomes
// theirs), then said to Smith, whose turn re-runs whichever owners it touches.
// See docs/plans/2026-10-08-huddle-room.md and backend/services/huddle/room.py.

import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { AGENT_BY_ID } from "@/components/virtual-office/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface Position {
  agent: string;
  view: string;
  change: string;
  needs: { agent: string; what: string }[];
  unavailable?: string;
}

interface HuddleRecord {
  id: string;
  kind: "review" | "deadlock";
  topic: string;
  participants: string[];
  chair: string;
  positions: Position[];
  decision: { decision?: string; reason?: string; question?: string; overruled?: string };
  status: "open" | "decided" | "deadlock" | "overruled";
  briefs: Record<string, string>;
  outcome: string[];
  at: string;
}

function nameOf(agent: string): string {
  return AGENT_BY_ID[agent]?.name ?? agent.replace(/_/g, " ");
}

function authHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

const STATUS: Record<HuddleRecord["status"], { label: string; tone: string }> = {
  open: { label: "Meeting", tone: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200" },
  decided: { label: "Decided", tone: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200" },
  deadlock: { label: "Needs you", tone: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200" },
  overruled: { label: "Your call", tone: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200" },
};

export function HuddleCards({
  projectId,
  tick,
  onOverrule,
  className,
}: {
  projectId: string;
  /** Changes whenever a huddle event arrives, so the record is read again. */
  tick: number;
  /** Says the overrule to Smith, as the person's own message. */
  onOverrule: (message: string) => void;
  className?: string;
}) {
  const [rows, setRows] = useState<HuddleRecord[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/projects/${projectId}/huddles`, {
        credentials: "include",
        headers: authHeaders(),
      });
      if (!res.ok) return;
      const body = (await res.json()) as { huddles?: HuddleRecord[] };
      setRows(Array.isArray(body.huddles) ? body.huddles : []);
    } catch {
      /* the record is shown when it can be read */
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load, tick]);

  const overrule = async (h: HuddleRecord) => {
    const words = (draft[h.id] ?? "").trim();
    if (!words) return;
    setBusy(h.id);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/projects/${projectId}/huddles/${h.id}/overrule`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ words }),
      });
      const body = (await res.json().catch(() => ({}))) as { message?: string; detail?: string };
      if (!res.ok) {
        setError(body.detail ?? "The overrule could not be recorded.");
        return;
      }
      setDraft((d) => ({ ...d, [h.id]: "" }));
      await load();
      if (body.message) onOverrule(body.message);
    } finally {
      setBusy(null);
    }
  };

  if (rows.length === 0) return null;

  return (
    <section className={cn("space-y-2", className)} aria-label="Huddles">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Huddles · {rows.length}
      </h3>
      {rows.map((h) => {
        const status = STATUS[h.status] ?? STATUS.open;
        const expanded = open === h.id;
        const said = h.decision.decision || h.decision.question || "";
        return (
          <article key={h.id} className="rounded-md border border-border bg-card p-3 text-sm">
            <button
              type="button"
              onClick={() => setOpen(expanded ? null : h.id)}
              className="flex w-full items-start gap-2 text-left"
              aria-expanded={expanded}
            >
              <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium", status.tone)}>
                {status.label}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium leading-snug">{h.topic}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {h.kind === "review" ? "Review" : "Deadlock"} · {h.participants.map(nameOf).join(", ")}
                  {" "}· chaired by {nameOf(h.chair)}
                </span>
              </span>
            </button>

            {said && (
              <p className="mt-2 leading-snug">
                {h.status === "deadlock" ? <span className="font-medium">Question: </span> : null}
                {said}
              </p>
            )}
            {h.decision.reason && h.status !== "deadlock" && (
              <p className="mt-1 text-xs text-muted-foreground">{h.decision.reason}</p>
            )}
            {h.status === "overruled" && h.decision.overruled && (
              <p className="mt-1 text-xs text-muted-foreground">
                The agents had decided: {h.decision.overruled}
              </p>
            )}

            {expanded && (
              <div className="mt-3 space-y-2 border-t border-border pt-2">
                {h.positions.map((p) => (
                  <div key={p.agent} className="text-xs">
                    <div className="font-medium">{nameOf(p.agent)}</div>
                    {p.unavailable ? (
                      <div className="text-muted-foreground">Could not answer.</div>
                    ) : (
                      <>
                        {p.view && <div className="text-muted-foreground">{p.view}</div>}
                        {p.change && <div>Would change: {p.change}</div>}
                        {p.needs.map((n, i) => (
                          <div key={i}>Needs from {nameOf(n.agent)}: {n.what}</div>
                        ))}
                      </>
                    )}
                  </div>
                ))}
                {h.outcome.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                    {h.outcome.map((o, i) => <li key={i}>{o}</li>)}
                  </ul>
                )}
              </div>
            )}

            {(h.status === "decided" || h.status === "deadlock") && (
              <div className="mt-3 flex gap-2">
                <label className="sr-only" htmlFor={`overrule-${h.id}`}>
                  {h.status === "deadlock" ? "Your answer" : "Decide otherwise"}
                </label>
                <input
                  id={`overrule-${h.id}`}
                  value={draft[h.id] ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, [h.id]: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === "Enter") void overrule(h); }}
                  placeholder={h.status === "deadlock" ? "Your answer…" : "Decide otherwise…"}
                  className="min-w-0 flex-1 rounded border border-border bg-background px-2 py-1 text-xs"
                />
                <button
                  type="button"
                  onClick={() => void overrule(h)}
                  disabled={busy === h.id || !(draft[h.id] ?? "").trim()}
                  className="rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground disabled:opacity-50"
                >
                  {h.status === "deadlock" ? "Answer" : "Overrule"}
                </button>
              </div>
            )}
          </article>
        );
      })}
      {error && <p className="text-xs text-rose-600">{error}</p>}
    </section>
  );
}
