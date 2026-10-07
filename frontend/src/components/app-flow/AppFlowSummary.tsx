"use client";

/**
 * The app flow in Smith's side panel: each person's paths as trails of the
 * screens they pass through, and the chosen one drawn live — before anything
 * is built, while the definition is waiting for a yes. "Open" takes the
 * path to the App Flow tab.
 */
import { useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, Maximize2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { flowsFromDoc } from "@/lib/appFlows";
import { useAppFlowStore } from "@/stores/appFlow";
import { FlowCanvas, hueFor, rolesOf } from "./AppFlowPanel";

const initials = (s: string) =>
  s.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";

export function AppFlowSummary({ doc }: { doc: Record<string, unknown> }) {
  const flows = useMemo(() => flowsFromDoc(doc), [doc]);
  const roles = useMemo(() => rolesOf(flows), [flows]);
  const [chosen, setChosen] = useState<string | null>(null);
  const open = useAppFlowStore((s) => s.open);
  const current = flows.find((f) => f.id === chosen) ?? flows[0];
  if (!flows.length) return null;

  return (
    <div className="space-y-3 px-4 pb-4">
      {/* The chosen path, drawn. */}
      <div className="overflow-hidden rounded-xl border bg-slate-50/70 dark:bg-slate-950/60">
        <div className="flex items-center justify-between gap-2 border-b bg-card/80 px-3 py-2">
          <div className="min-w-0">
            <div className="truncate text-xs font-semibold">{current.name}</div>
            {current.goal && <div className="truncate text-[11px] text-muted-foreground">{current.goal}</div>}
          </div>
          <button type="button" onClick={() => open(current.id)}
            className="inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground">
            <Maximize2 className="h-3 w-3" /> Open
          </button>
        </div>
        <div className="h-64 bg-[radial-gradient(ellipse_at_top,rgba(251,146,60,0.08),transparent_60%)]">
          <FlowCanvas flows={flows} chosen={current.id} compact />
        </div>
      </div>

      {/* Every path, by person. */}
      {roles.map((role) => {
        const hue = hueFor(roles, role);
        const mine = flows.filter((f) => (f.role || "Everyone") === role);
        return (
          <div key={role}>
            <div className="mb-1.5 flex items-center gap-2">
              <span className={cn("flex h-5 w-5 items-center justify-center rounded-full text-[9px] font-bold text-white", hue.badge)}>
                {initials(role)}
              </span>
              <span className="text-xs font-semibold">{role}</span>
              <span className="text-[11px] text-muted-foreground">{mine.length}</span>
            </div>
            <ul className="space-y-1">
              {mine.map((f) => (
                <li key={f.id}>
                  <button type="button" onClick={() => setChosen(f.id)}
                    className={cn("w-full rounded-lg border px-2.5 py-1.5 text-left transition hover:bg-muted/50",
                      current.id === f.id ? cn("border-transparent ring-2", hue.ring) : "border-border")}>
                    <div className="truncate text-[12px] font-medium">{f.name}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-1 text-[10.5px] text-muted-foreground">
                      {f.nodes.map((n, i) => (
                        <span key={n.id} className="inline-flex items-center gap-1">
                          <span className={cn("inline-flex items-center gap-1 rounded px-1 py-px",
                            n.last ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300"
                              : "bg-muted text-foreground/80")}>
                            {n.last && <CheckCircle2 className="h-2.5 w-2.5" />}
                            {n.screen}{n.part ? ` · ${n.part}` : ""}
                          </span>
                          {i < f.nodes.length - 1 && <ArrowRight className="h-2.5 w-2.5 shrink-0" />}
                        </span>
                      ))}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

export default AppFlowSummary;
