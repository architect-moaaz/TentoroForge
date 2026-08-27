"use client";

import { useEffect, useState } from "react";
import {
  Wrench,
  ChevronDown,
  ChevronRight,
  ArrowRight,
  FileCode2,
  Loader2,
  Check,
  Plus,
  Minus,
  Pencil,
  Sparkles,
} from "lucide-react";
import type { FixProposal, FixChange } from "@/stores/chat";

interface FixProposalCardProps {
  proposal: FixProposal;
  onApply: (token: string) => void;
  /** True once this proposal has been applied (fix_applied arrived). */
  applied?: boolean;
  /** True while a stream is in flight (apply POST running). */
  disabled?: boolean;
}

/** Render a value (from/to) compactly for the change preview. */
function renderValue(v: unknown): string {
  if (v === null || v === undefined) return "∅";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

function confidenceLabel(c: number | string | undefined): string | null {
  if (c === undefined || c === null) return null;
  if (typeof c === "number") {
    const pct = c <= 1 ? Math.round(c * 100) : Math.round(c);
    return `${pct}% confidence`;
  }
  return `${c} confidence`;
}

/** Visual verb for a change based on its kind. `kind` is populated by the
 *  add_page / add_workflow / add_entity seams (`add` = new file);
 *  workflow_node_config / page_schema_patch proposals have from/to fields.
 *  Everything else falls back to a neutral "change" mark. */
function changeVerb(change: FixChange): {
  Icon: typeof Plus;
  label: string;
  color: string;
  bg: string;
} {
  const kind = (change as unknown as { kind?: string }).kind;
  const hasFromTo = "from" in change || "to" in change;
  if (kind === "add") {
    return { Icon: Plus, label: "add", color: "text-emerald-700", bg: "bg-emerald-50" };
  }
  if (kind === "delete" || kind === "remove") {
    return { Icon: Minus, label: "remove", color: "text-red-700", bg: "bg-red-50" };
  }
  if (hasFromTo) {
    return { Icon: Pencil, label: "modify", color: "text-amber-700", bg: "bg-amber-50" };
  }
  return { Icon: Pencil, label: "change", color: "text-muted-foreground", bg: "bg-muted" };
}

function ChangeRow({ change }: { change: FixChange }) {
  const hasFromTo = "from" in change || "to" in change;
  const verb = changeVerb(change);

  return (
    <div className="rounded-md border bg-muted/40 px-2.5 py-1.5">
      {(change.label || change.path) && (
        <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-foreground">
          <span
            className={`inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] font-medium ${verb.bg} ${verb.color}`}
            title={verb.label}
          >
            <verb.Icon className="h-2.5 w-2.5" />
            {verb.label}
          </span>
          {change.path && (
            <code className="rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
              {change.path}
            </code>
          )}
          {change.label && <span>{change.label}</span>}
        </div>
      )}
      {hasFromTo ? (
        <div className="flex items-center gap-2 text-[11px]">
          <code className="min-w-0 truncate rounded bg-red-50 px-1.5 py-0.5 text-red-700 line-through">
            {renderValue(change.from)}
          </code>
          <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground" />
          <code className="min-w-0 truncate rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700">
            {renderValue(change.to)}
          </code>
        </div>
      ) : (
        change.description && (
          <p className="text-[11px] text-muted-foreground">{change.description}</p>
        )
      )}
    </div>
  );
}

/** True when every change in the list is an `add` — used to switch the
 *  card header from "Proposed fix" to "New page" for add_page proposals. */
function allChangesAreAdds(changes: FixChange[] | undefined): boolean {
  if (!Array.isArray(changes) || changes.length === 0) return false;
  return changes.every((c) => (c as unknown as { kind?: string }).kind === "add");
}

export function FixProposalCard({
  proposal,
  onApply,
  applied,
  disabled,
}: FixProposalCardProps) {
  // Three states: idle → applying (spinner) → applied (check) OR stale
  // (warning). The click flips to "applying" only; ONLY the backend's
  // `fix_applied` event (which sets the `applied` prop above us) flips
  // to "applied". This is the fix for the class of bug where the UI
  // said "Applied ✓" while the backend committed nothing.
  const [applying, setApplying] = useState(false);
  const [stale, setStale] = useState(false);
  const { diagnosis, changes, applyToken } = proposal;
  // "Add" proposals expand by default so users see the file list up front;
  // "modify" proposals stay collapsed (the changes are inline in from/to
  // rows and can get long).
  const defaultExpanded = allChangesAreAdds(changes);
  const [expanded, setExpanded] = useState(defaultExpanded);
  const conf = confidenceLabel(diagnosis?.confidence);
  const artifactPath = diagnosis?.artifact?.path;
  const isApplied = applied === true;

  // When the backend confirms, drop the applying state.
  useEffect(() => {
    if (applied) {
      setApplying(false);
      setStale(false);
    }
  }, [applied]);

  // If the user clicked apply but no fix_applied has arrived after 45s,
  // flip to a "stale" state so they know the confirmation didn't land.
  // 45s is generous — Smith's slower turns can hit ~25s of thinking
  // before the applier runs.
  useEffect(() => {
    if (!applying || applied) return;
    const t = setTimeout(() => setStale(true), 45000);
    return () => clearTimeout(t);
  }, [applying, applied]);

  // Distinguish add_page / add_workflow-style "new thing" proposals from
  // fix-style "modify existing" proposals: the header, icon, gradient,
  // and default expanded-state all change.
  const isNewThing = allChangesAreAdds(changes);
  const HeaderIcon = isNewThing ? Sparkles : Wrench;

  return (
    <div className="my-2 rounded-lg border bg-card shadow-sm">
      {/* Header */}
      <div
        className={`border-b px-4 py-3 ${
          isNewThing
            ? "bg-gradient-to-r from-emerald-50 to-teal-50"
            : "bg-gradient-to-r from-amber-50 to-orange-50"
        }`}
      >
        <div className="flex items-center gap-2">
          <HeaderIcon
            className={`h-4 w-4 ${isNewThing ? "text-emerald-600" : "text-amber-600"}`}
          />
          <h3
            className={`text-sm font-semibold ${
              isNewThing ? "text-emerald-900" : "text-amber-900"
            }`}
          >
            {isNewThing ? "Proposed addition" : "Proposed fix"}
          </h3>
          {diagnosis?.feature && (
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                isNewThing
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-amber-100 text-amber-700"
              }`}
            >
              {diagnosis.feature}
            </span>
          )}
        </div>
        {diagnosis?.explanation && (
          <p
            className={`mt-1.5 text-xs leading-relaxed ${
              isNewThing ? "text-emerald-900/80" : "text-amber-900/80"
            }`}
          >
            {diagnosis.explanation}
          </p>
        )}
      </div>

      <div className="divide-y text-xs">
        {/* Root cause */}
        {diagnosis?.rootCause && (
          <div className="px-4 py-2.5">
            <div className="mb-1 font-medium text-muted-foreground">
              Root cause
            </div>
            <p className="text-foreground">{diagnosis.rootCause}</p>
          </div>
        )}

        {/* What will change (collapsible) */}
        {Array.isArray(changes) && changes.length > 0 && (
          <div className="px-4 py-2.5">
            <button
              onClick={() => setExpanded((e) => !e)}
              className="flex w-full items-center gap-1.5 font-medium text-muted-foreground hover:text-foreground"
            >
              {expanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              What will change ({changes.length})
            </button>
            {expanded && (
              <div className="mt-2 space-y-1.5">
                {changes.map((change, i) => (
                  <ChangeRow key={i} change={change} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer: artifact + confidence + apply */}
      <div className="flex flex-wrap items-center gap-3 border-t px-4 py-3">
        <button
          onClick={() => {
            if (isApplied || applying) return;
            setApplying(true);
            setStale(false);
            onApply(applyToken || "[APPLY_FIX]");
          }}
          disabled={disabled || isApplied || applying}
          className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-white shadow-sm disabled:opacity-50 ${
            stale
              ? "bg-gradient-to-r from-red-500 to-red-600"
              : isNewThing
                ? "bg-gradient-to-r from-emerald-500 to-emerald-600 hover:from-emerald-600 hover:to-emerald-700"
                : "bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-600 hover:to-amber-700"
          }`}
        >
          {isApplied ? (
            <Check className="h-3 w-3" />
          ) : applying ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : isNewThing ? (
            <Sparkles className="h-3 w-3" />
          ) : (
            <Wrench className="h-3 w-3" />
          )}
          {isApplied
            ? "Applied"
            : applying
              ? stale
                ? "May not have landed"
                : "Applying…"
              : isNewThing
                ? "Add it"
                : "Apply fix"}
        </button>

        {stale && !isApplied && (
          <span
            className="text-[10px] text-red-600"
            title="The backend hasn't confirmed this apply within 45 seconds. It may have failed silently — check the file history before assuming."
          >
            no confirmation from backend — check git history
          </span>
        )}

        <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
          {artifactPath && (
            <span className="inline-flex items-center gap-1">
              <FileCode2 className="h-3 w-3" />
              <code className="truncate">{artifactPath}</code>
            </span>
          )}
          {conf && <span>{conf}</span>}
        </div>
      </div>
    </div>
  );
}
