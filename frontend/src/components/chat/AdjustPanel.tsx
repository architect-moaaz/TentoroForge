"use client";

/**
 * Inline conversational panel for the Adjust-strategy flow.
 *
 * When the user clicks "Adjust strategy" on a PlanCard, the card
 * mounts this panel below its content. Each turn hits the backend
 * `POST /api/projects/{id}/plan/adjust` endpoint, which returns the
 * new plan + structured diff. Parent (PlanCard) re-renders when the
 * plan changes; this panel just shows the conversation timeline and
 * whatever the last mutation touched.
 *
 * Reliability contract: the backend is the single source of truth.
 * We only send messages + display responses. No optimistic mutation
 * on the client — a message either lands (plan updates) or errors
 * (message stays visible with the error underneath).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { MessageSquare, Loader2, AlertCircle, Send, X } from "lucide-react";
import { useAuthStore } from "@/stores/auth";

interface AdjustDiff {
  // Plan-adjust diff keys
  entities_added?: string[];
  entities_removed?: string[];
  pages_added?: string[];
  pages_removed?: string[];
  workflows_added?: string[];
  workflows_removed?: string[];
  actors_added?: string[];
  actors_removed?: string[];
  features_added?: string[];
  features_removed?: string[];
  // Discovery-adjust diff keys
  compliance_added?: string[];
  compliance_removed?: string[];
  patterns_added?: string[];
  patterns_removed?: string[];
  pitfalls_added?: string[];
  pitfalls_removed?: string[];
  domain_changed?: boolean;
  description_changed?: boolean;
  visual_changed?: boolean;
}

interface AdjustResponse {
  // plan set on plan-target responses; discovery set on discovery-target ones
  plan?: Record<string, unknown>;
  discovery?: Record<string, unknown>;
  diff: AdjustDiff;
  applied_ops: { op: string; args: Record<string, unknown> }[];
  narrative: string;
  warnings: string[];
  error?: string | null;
}

export type AdjustTarget = "plan" | "discovery";

type TurnKind = "user" | "assistant" | "error";

interface Turn {
  kind: TurnKind;
  text: string;
  diff?: AdjustDiff;
  warnings?: string[];
}

interface AdjustPanelProps {
  projectId: string;
  /** Called with the new plan/dossier document after each successful turn. */
  onPlanUpdated: (updated: Record<string, unknown>) => void;
  onClose: () => void;
  disabled?: boolean;
  /** Which artefact this panel is adjusting. Defaults to "plan" so
   *  existing PlanCard callers keep working unchanged. */
  target?: AdjustTarget;
}

const PLAN_EXAMPLES = [
  'Add a bookings entity with rooms and dates',
  'Remove the Notifications workflow',
  'Add a Reviewer role',
  'Turn on commerce',
];

const DISCOVERY_EXAMPLES = [
  'Change the domain to Hospitality',
  'Add PCI compliance',
  'Suggest a Reservation entity',
  'Drop the "Undifferentiated status labels" pitfall',
];

export function AdjustPanel({
  projectId,
  onPlanUpdated,
  onClose,
  disabled,
  target = "plan",
}: AdjustPanelProps) {
  const endpoint =
    target === "discovery"
      ? `/api/projects/${projectId}/discovery/adjust`
      : `/api/projects/${projectId}/plan/adjust`;
  const headline =
    target === "discovery"
      ? "Tell Smith what to change in the dossier"
      : "Tell Smith what to change";
  const examples = target === "discovery" ? DISCOVERY_EXAMPLES : PLAN_EXAMPLES;
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const token = useAuthStore((s) => s.token);

  // Keep the timeline pinned to the bottom as new turns land.
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [turns.length, busy]);

  const submit = useCallback(async () => {
    const msg = input.trim();
    if (!msg || busy) return;
    setTurns((prev) => [...prev, { kind: "user", text: msg }]);
    setInput("");
    setBusy(true);
    try {
      const res = await fetch(
        endpoint,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ message: msg }),
        },
      );
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        setTurns((prev) => [
          ...prev,
          { kind: "error", text: text || `HTTP ${res.status}` },
        ]);
        return;
      }
      const data: AdjustResponse = await res.json();
      if (data.error) {
        setTurns((prev) => [
          ...prev,
          { kind: "error", text: data.narrative || data.error! },
        ]);
        return;
      }
      setTurns((prev) => [
        ...prev,
        {
          kind: "assistant",
          text: data.narrative || "Adjustment applied.",
          diff: data.diff,
          warnings: data.warnings,
        },
      ]);
      const updated =
        target === "discovery" ? data.discovery : data.plan;
      if (updated) onPlanUpdated(updated);
    } catch (e) {
      const err = e instanceof Error ? e.message : String(e);
      setTurns((prev) => [...prev, { kind: "error", text: err }]);
    } finally {
      setBusy(false);
    }
  }, [busy, input, endpoint, target, onPlanUpdated, token]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void submit();
      }
    },
    [submit],
  );

  return (
    <div className="border-t bg-muted/30">
      {/* Header */}
      <div className="flex items-center justify-between border-b bg-background/50 px-4 py-2">
        <div className="flex items-center gap-2 text-xs font-medium text-foreground">
          <MessageSquare className="h-3.5 w-3.5 text-indigo-500" />
          {headline}
        </div>
        <button
          onClick={onClose}
          disabled={busy}
          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
          aria-label="Close Adjust panel"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Timeline */}
      <div
        ref={scrollRef}
        className="max-h-72 overflow-y-auto px-4 py-3 space-y-3"
      >
        {turns.length === 0 && (
          <div className="text-xs text-muted-foreground leading-relaxed">
            Chat with Smith to refine the{" "}
            {target === "discovery" ? "domain dossier" : "plan"}. Try things
            like:
            <ul className="mt-1.5 ml-4 space-y-0.5 list-disc">
              {examples.map((ex) => (
                <li key={ex}>&quot;{ex}&quot;</li>
              ))}
            </ul>
            {target === "discovery"
              ? "Each change updates the dossier in place — pick Build Fast or Build Complete when it looks right."
              : "Each change updates the plan in place — hit Begin Quest when it looks right."}
          </div>
        )}
        {turns.map((t, i) => (
          <TurnRow key={i} turn={t} />
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Applying…
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t bg-background/50 px-3 py-2">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={busy || disabled}
            rows={1}
            placeholder="What should change?"
            className="min-h-[2rem] max-h-32 flex-1 resize-none rounded-md border bg-background px-3 py-1.5 text-xs shadow-sm outline-none placeholder:text-muted-foreground/70 focus:ring-1 focus:ring-indigo-500 disabled:opacity-50"
          />
          <button
            onClick={() => void submit()}
            disabled={busy || disabled || !input.trim()}
            className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
          >
            <Send className="h-3 w-3" />
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// TurnRow — renders one entry in the timeline.                                //
// --------------------------------------------------------------------------- //

function TurnRow({ turn }: { turn: Turn }) {
  if (turn.kind === "user") {
    return (
      <div className="flex justify-end">
        <div className="rounded-lg bg-indigo-600 text-white text-xs px-3 py-1.5 max-w-[80%] leading-snug">
          {turn.text}
        </div>
      </div>
    );
  }
  if (turn.kind === "error") {
    return (
      <div className="flex items-start gap-1.5 text-xs text-red-600">
        <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        <span>{turn.text}</span>
      </div>
    );
  }
  return (
    <div className="rounded-lg bg-background border px-3 py-2 max-w-[90%] text-xs leading-snug">
      <div className="text-foreground">{turn.text}</div>
      {turn.diff && !isEmptyDiff(turn.diff) && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          <Chips label="+ entity" items={turn.diff.entities_added} tone="add" />
          <Chips
            label="- entity"
            items={turn.diff.entities_removed}
            tone="remove"
          />
          <Chips label="+ page" items={turn.diff.pages_added} tone="add" />
          <Chips label="- page" items={turn.diff.pages_removed} tone="remove" />
          <Chips
            label="+ workflow"
            items={turn.diff.workflows_added}
            tone="add"
          />
          <Chips
            label="- workflow"
            items={turn.diff.workflows_removed}
            tone="remove"
          />
          <Chips label="+ actor" items={turn.diff.actors_added} tone="add" />
          <Chips
            label="- actor"
            items={turn.diff.actors_removed}
            tone="remove"
          />
          <Chips
            label="+ feature"
            items={turn.diff.features_added}
            tone="add"
          />
          <Chips
            label="- feature"
            items={turn.diff.features_removed}
            tone="remove"
          />
          {/* Discovery-adjust diff chips */}
          <Chips
            label="+ compliance"
            items={turn.diff.compliance_added}
            tone="add"
          />
          <Chips
            label="- compliance"
            items={turn.diff.compliance_removed}
            tone="remove"
          />
          <Chips
            label="+ pattern"
            items={turn.diff.patterns_added}
            tone="add"
          />
          <Chips
            label="- pattern"
            items={turn.diff.patterns_removed}
            tone="remove"
          />
          <Chips
            label="+ pitfall"
            items={turn.diff.pitfalls_added}
            tone="add"
          />
          <Chips
            label="- pitfall"
            items={turn.diff.pitfalls_removed}
            tone="remove"
          />
          {turn.diff.domain_changed && (
            <span className="inline-flex items-center rounded-md border border-blue-200 bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-800">
              ~ domain
            </span>
          )}
          {turn.diff.description_changed && (
            <span className="inline-flex items-center rounded-md border border-blue-200 bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-800">
              ~ description
            </span>
          )}
          {turn.diff.visual_changed && (
            <span className="inline-flex items-center rounded-md border border-blue-200 bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-800">
              ~ visual language
            </span>
          )}
        </div>
      )}
      {turn.warnings && turn.warnings.length > 0 && (
        <div className="mt-1.5 text-[11px] text-amber-700">
          {turn.warnings.map((w, i) => (
            <div key={i}>⚠ {w}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function Chips({
  label,
  items,
  tone,
}: {
  label: string;
  items?: string[];
  tone: "add" | "remove";
}) {
  if (!items || items.length === 0) return null;
  const cls =
    tone === "add"
      ? "bg-emerald-100 text-emerald-800 border-emerald-200"
      : "bg-red-100 text-red-800 border-red-200";
  return (
    <>
      {items.map((it) => (
        <span
          key={`${label}-${it}`}
          className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${cls}`}
        >
          {label} {it}
        </span>
      ))}
    </>
  );
}

function isEmptyDiff(d: AdjustDiff): boolean {
  return (
    !d.entities_added?.length &&
    !d.entities_removed?.length &&
    !d.pages_added?.length &&
    !d.pages_removed?.length &&
    !d.workflows_added?.length &&
    !d.workflows_removed?.length &&
    !d.actors_added?.length &&
    !d.actors_removed?.length &&
    !d.features_added?.length &&
    !d.features_removed?.length &&
    !d.compliance_added?.length &&
    !d.compliance_removed?.length &&
    !d.patterns_added?.length &&
    !d.patterns_removed?.length &&
    !d.pitfalls_added?.length &&
    !d.pitfalls_removed?.length &&
    !d.domain_changed &&
    !d.description_changed &&
    !d.visual_changed
  );
}
