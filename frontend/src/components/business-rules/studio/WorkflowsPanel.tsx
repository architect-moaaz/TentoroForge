"use client";

// Where a rule acts beyond the record's own saves, and running it as a step
// of a workflow — the business-rule task of a process: a table computes values
// the steps after it use; a rule that can refuse is a gate.

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { GitBranch, Loader2, Plus, ShieldCheck, Workflow, X } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { problemsOf } from "@/lib/blueprint-rules";
import type { StudioCatalogue, StudioView } from "@/lib/rules-studio";

export function WorkflowsPanel({ projectId, view, catalogue, onChanged, unsaved }: {
  projectId: string;
  view: StudioView | null;
  catalogue: StudioCatalogue | null;
  onChanged: () => void;
  unsaved?: boolean;
}) {
  const [flow, setFlow] = useState("");
  const [after, setAfter] = useState<string>("__start");
  const [onRefusal, setOnRefusal] = useState<"stop" | "continue">("stop");
  const u = view?.usages ?? { steps: [], starts: [], saves: [] };
  const rule = view?.rule;
  const isGate = !!rule && view?.kind === "condition_action" &&
    [...(rule.then ?? []), ...(rule.otherwise ?? [])].some((a: any) => a?.type === "show_error");
  const steps = useMemo(() => (catalogue?.workflows.find((w) => w.id === flow)?.steps ?? [])
    .filter((s) => !["end", "end_event"].includes(String(s.type)) && !s.key.startsWith("rule_")), [catalogue, flow]);

  const attach = useMutation({
    mutationFn: () => api.post(`/api/projects/${projectId}/business-rules/${rule!.id}/workflows`, {
      workflow: flow, after: after === "__start" ? null : after, on_refusal: onRefusal,
    }),
    onSuccess: () => {
      toast.success("It runs in that workflow now — in your app at once.");
      setFlow(""); setAfter("__start"); onChanged();
    },
    onError: (e) => toast.error(problemsOf(e)[0]),
  });
  const detach = useMutation({
    mutationFn: (wid: string) => api.delete(`/api/projects/${projectId}/business-rules/${rule!.id}/workflows/${wid}`),
    onSuccess: () => { toast.success("Taken out of that workflow."); onChanged(); },
    onError: (e) => toast.error(problemsOf(e)[0]),
  });

  if (unsaved || !view) {
    return <p className="text-xs text-muted-foreground">Save the rule, then choose the workflows it runs in.</p>;
  }
  if (view.kind !== "condition_action" && view.kind !== "decision_table") {
    return <p className="text-xs text-muted-foreground">A written rule is not checked by the app, so it cannot run in a workflow yet.</p>;
  }

  return (
    <div className="space-y-3 text-xs" data-testid="workflows-panel">
      <div className="space-y-1.5">
        <p className="font-medium">Runs as a step in</p>
        {u.steps.length === 0 ? <p className="text-muted-foreground">No workflow yet.</p> : (
          <ul className="space-y-1">
            {u.steps.map((s) => (
              <li key={s.workflow} className="flex items-center gap-2 rounded-md border px-2 py-1.5">
                <GitBranch className="h-3.5 w-3.5 text-violet-600" />
                <span className="font-medium">{s.name}</span>
                <span className="text-muted-foreground">{s.stops ? "· stops it when the rule refuses" : "· carries on either way"}</span>
                <button type="button" onClick={() => detach.mutate(s.workflow)} disabled={detach.isPending}
                        aria-label={`Stop running it in ${s.name}`} className="ml-auto text-muted-foreground hover:text-destructive">
                  <X className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {u.saves.length > 0 && (
        <div className="space-y-1">
          <p className="flex items-center gap-1.5 font-medium"><ShieldCheck className="h-3.5 w-3.5 text-emerald-600" /> Also checked whenever these save {view.entityName ? `a ${view.entityName}` : "the record"}</p>
          <p className="text-muted-foreground">{u.saves.map((s) => s.name).join(" · ")}</p>
        </div>
      )}
      {u.starts.length > 0 && (
        <div className="space-y-1">
          <p className="flex items-center gap-1.5 font-medium"><Workflow className="h-3.5 w-3.5" /> Starts</p>
          <p className="text-muted-foreground">{u.starts.map((s) => s.name).join(" · ")}</p>
        </div>
      )}

      <div className="space-y-2 rounded-lg border bg-muted/30 p-2.5">
        <p className="font-medium">Run it in a workflow</p>
        <select aria-label="Workflow" value={flow} onChange={(e) => { setFlow(e.target.value); setAfter("__start"); }}
                className="h-8 w-full rounded-md border bg-background px-2">
          <option value="">Choose a workflow…</option>
          {(catalogue?.workflows ?? []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
        </select>
        {flow && (
          <>
            <label className="block space-y-1">
              <span className="text-muted-foreground">Check it</span>
              <select aria-label="After step" value={after} onChange={(e) => setAfter(e.target.value)}
                      className="h-8 w-full rounded-md border bg-background px-2">
                <option value="__start">at the start</option>
                {steps.map((s) => <option key={s.key} value={s.key}>after “{s.name}”</option>)}
              </select>
            </label>
            {isGate ? (
              <fieldset className="space-y-1">
                <legend className="text-muted-foreground">When the rule refuses</legend>
                {([["stop", "stop the workflow with the rule’s message"], ["continue", "carry on anyway"]] as const).map(([v, label]) => (
                  <label key={v} className="flex items-center gap-2">
                    <input type="radio" name="on_refusal" checked={onRefusal === v} onChange={() => setOnRefusal(v)} /> {label}
                  </label>
                ))}
              </fieldset>
            ) : view.kind === "decision_table" ? (
              <p className="text-muted-foreground">The values it sets are used by the steps after it.</p>
            ) : null}
            <Button size="sm" className="w-full" onClick={() => attach.mutate()} disabled={attach.isPending}>
              {attach.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Plus className="mr-1.5 h-3.5 w-3.5" />}
              Add to this workflow
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
