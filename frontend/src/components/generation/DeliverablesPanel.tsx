"use client";

import {
  Database,
  GitBranch,
  Layout,
  PlugZap,
  ClipboardList,
  CircleCheck,
  Loader2,
  Circle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ResourceCard, ResourceKind } from "@/stores/chat";

/** The big deliverables, in pipeline order. `plan` has no resource events yet —
 *  it's marked done as soon as any later resource arrives. */
const TRACK: { kind: ResourceKind | "plan"; label: string; icon: LucideIcon }[] = [
  { kind: "plan", label: "Plan", icon: ClipboardList },
  { kind: "data_model", label: "Data models", icon: Database },
  { kind: "workflow", label: "Workflows", icon: GitBranch },
  { kind: "page", label: "Pages", icon: Layout },
  { kind: "binding", label: "Bindings", icon: PlugZap },
];

const KIND_ICON: Record<ResourceKind, LucideIcon> = {
  data_model: Database,
  workflow: GitBranch,
  page: Layout,
  binding: PlugZap,
};

const KIND_TINT: Record<ResourceKind, string> = {
  data_model: "bg-teal-100 text-teal-700",
  workflow: "bg-violet-100 text-violet-700",
  page: "bg-blue-100 text-blue-700",
  binding: "bg-emerald-100 text-emerald-700",
};

type TrackState = "queued" | "active" | "done";

/** Derive per-deliverable state from the resource cards received so far. */
function trackStates(resources: ResourceCard[], isGenerating: boolean): Record<string, TrackState> {
  const byKind = new Map<ResourceKind, ResourceCard[]>();
  for (const r of resources) {
    const arr = byKind.get(r.kind) ?? [];
    arr.push(r);
    byKind.set(r.kind, arr);
  }
  const order: ResourceKind[] = ["data_model", "workflow", "page", "binding"];
  const lastWithAny = order.reduce((acc, k, i) => (byKind.has(k) ? i : acc), -1);

  const out: Record<string, TrackState> = {};
  // Plan is done the moment any resource has streamed (or generation ended).
  out.plan = resources.length > 0 || !isGenerating ? "done" : "active";
  order.forEach((k, i) => {
    const cards = byKind.get(k) ?? [];
    if (cards.length === 0) {
      out[k] = "queued";
    } else if (i < lastWithAny) {
      out[k] = "done"; // a later stage has started → this one's finished
    } else {
      // Newest stage: done only when every card is done AND generation moved on.
      const allDone = cards.every((c) => c.state === "done");
      out[k] = allDone && !isGenerating ? "done" : "active";
    }
  });
  return out;
}

function StateDot({ state }: { state: TrackState }) {
  if (state === "done") return <CircleCheck className="h-4 w-4 text-emerald-500" />;
  if (state === "active") return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
  return <Circle className="h-4 w-4 text-muted-foreground/40" />;
}

export function DeliverablesPanel({
  resources,
  isGenerating,
  maxCards = 5,
}: {
  resources: ResourceCard[];
  isGenerating: boolean;
  maxCards?: number;
}) {
  if (resources.length === 0) return null;
  const states = trackStates(resources, isGenerating);
  const recent = resources.slice(-maxCards).reverse(); // newest first

  return (
    <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,150px)_1fr]">
      {/* Deliverables tracker */}
      <div className="flex flex-col gap-1">
        {TRACK.map((t) => {
          const st = states[t.kind] ?? "queued";
          const Icon = t.icon;
          return (
            <div
              key={t.kind}
              className={`flex items-center gap-2 rounded-md px-2 py-1.5 ${
                st === "active" ? "bg-muted/60" : ""
              }`}
            >
              <StateDot state={st} />
              <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span
                className={`text-xs ${
                  st === "queued"
                    ? "text-muted-foreground/60"
                    : st === "active"
                      ? "font-medium text-foreground"
                      : "text-foreground"
                }`}
              >
                {t.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Live preview cards */}
      <div className="flex flex-col gap-1.5">
        {recent.map((r, i) => {
          const Icon = KIND_ICON[r.kind];
          return (
            <div
              key={`${r.kind}:${r.name}:${i}`}
              className="animate-in fade-in slide-in-from-bottom-1 flex items-center gap-2.5 rounded-xl border border-border/70 bg-card px-2.5 py-2 duration-300"
            >
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-lg ${KIND_TINT[r.kind]}`}
              >
                <Icon className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-foreground">{r.name}</p>
                {r.summary && (
                  <p className="truncate text-[10px] text-muted-foreground">{r.summary}</p>
                )}
              </div>
              {r.index != null && r.total != null && (
                <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/60">
                  {r.index}/{r.total}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
