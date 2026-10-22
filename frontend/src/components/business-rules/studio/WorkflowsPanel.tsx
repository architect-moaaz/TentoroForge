"use client";

// WHERE A RULE IS USED. A rule about a record is checked by the app every
// time any workflow saves that record — nobody has to connect it by hand.
// So this panel first lists those workflows (worked out by the server from
// the app's definition: services/rule_links.py), then anything that needs
// the person: a workflow's own older check on the same fields that no longer
// matches the rule ("use this rule instead"), and the extra check steps
// someone added. Adding an extra, earlier check is an advanced option, offered
// only in the workflows that save this record.

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, ChevronDown, GitBranch, Loader2, Plus, Workflow, X } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { problemsOf } from "@/lib/blueprint-rules";
import type { RuleLink, StudioCatalogue, StudioView } from "@/lib/rules-studio";

const an = (noun: string) => `${/^[aeiou]/i.test(noun) ? "an" : "a"} ${noun}`;

/** "when it saves a new expense" / "when it saves changes to an expense". */
function whenSaid(l: RuleLink, record: string) {
  return l.event === "create" ? `when it saves a new ${record}` : `when it saves changes to ${an(record)}`;
}

export function WorkflowsPanel({ projectId, view, catalogue, onChanged, unsaved, onOpenWorkflow }: {
  projectId: string;
  view: StudioView | null;
  catalogue: StudioCatalogue | null;
  onChanged: () => void;
  unsaved?: boolean;
  /** Open a workflow in the Workflows tab, when the page can. */
  onOpenWorkflow?: (workflowId: string) => void;
}) {
  const [more, setMore] = useState(false);
  const [flow, setFlow] = useState("");
  const [after, setAfter] = useState<string>("__start");
  const [onStop, setOnStop] = useState<"stop" | "continue">("stop");
  const u = view?.usages ?? { steps: [], starts: [], saves: [] };
  const links = u.links ?? [];
  const copies = u.copies ?? [];
  const rule = view?.rule;
  const record = (view?.entityName ?? "record").toLowerCase();
  const acts = [...(rule?.then ?? []), ...(rule?.otherwise ?? [])] as Array<Record<string, unknown>>;
  // A rule that can stop a save: a message, or a field it makes required.
  const canStop = view?.kind === "condition_action" &&
    acts.some((a) => a?.type === "show_error" || (a?.type === "set_required" && a?.required !== false));
  const onlyFills = view?.kind === "condition_action" && !canStop;
  const main = links.filter((l) => l.touches);
  const also = links.filter((l) => !l.touches);
  // An extra step makes sense only in a workflow that saves this record.
  const flows = useMemo(() => {
    const ids = new Set(links.map((l) => l.workflow));
    return (catalogue?.workflows ?? []).filter((w) => ids.has(w.id));
  }, [catalogue, links]);
  const steps = useMemo(() => (catalogue?.workflows.find((w) => w.id === flow)?.steps ?? [])
    .filter((s) => !["end", "end_event"].includes(String(s.type)) && !s.key.startsWith("rule_")), [catalogue, flow]);

  const attach = useMutation({
    mutationFn: () => api.post(`/api/projects/${projectId}/business-rules/${rule!.id}/workflows`, {
      workflow: flow, after: after === "__start" ? null : after.split("|")[0],
      path: after.endsWith("|else") ? "else" : "then", on_refusal: onStop,
    }),
    onSuccess: () => {
      toast.success("Extra check added to that workflow. Your app uses it right away.");
      setFlow(""); setAfter("__start"); setOnStop("stop"); setMore(false); onChanged();
    },
    onError: (e) => toast.error(problemsOf(e)[0]),
  });
  const detach = useMutation({
    mutationFn: (wid: string) => api.delete(`/api/projects/${projectId}/business-rules/${rule!.id}/workflows/${wid}`),
    onSuccess: () => { toast.success("Extra check removed from that workflow."); onChanged(); },
    onError: (e) => toast.error(problemsOf(e)[0]),
  });
  const follow = useMutation({
    mutationFn: (c: { workflow: string; step: string }) =>
      api.post(`/api/projects/${projectId}/business-rules/${rule!.id}/workflows/${c.workflow}/follow`, { step: c.step }),
    onSuccess: () => { toast.success("Done. That workflow now follows this rule."); onChanged(); },
    onError: (e) => toast.error(problemsOf(e)[0]),
  });

  if (unsaved || !view) {
    return <p className="text-xs text-muted-foreground">Save the rule first. Then you will see every workflow that uses it.</p>;
  }
  if (view.kind !== "condition_action" && view.kind !== "decision_table") {
    return <p className="text-xs text-muted-foreground">This is a note, so the app does not check it and no workflow uses it.</p>;
  }
  if (!view.enabled) {
    return <p className="text-xs text-muted-foreground">This rule is turned off, so no workflow uses it. Turn it on to use it again.</p>;
  }

  const WorkflowName = ({ id, name }: { id: string; name: string }) => onOpenWorkflow ? (
    <button type="button" onClick={() => onOpenWorkflow(id)} className="font-medium text-left hover:underline">{name}</button>
  ) : <span className="font-medium">{name}</span>;

  return (
    <div className="space-y-3 text-xs" data-testid="workflows-panel">
      {links.length === 0 ? (
        <p className="rounded-md border bg-background px-2.5 py-2 text-muted-foreground" data-testid="no-links">
          No workflow saves {an(record)} yet. The rule is still checked every time {an(record)} is saved from a screen.
        </p>
      ) : (
        <div className="space-y-1.5">
          <p className="flex items-center gap-1.5 font-medium text-emerald-800 dark:text-emerald-300">
            <CheckCircle2 className="h-3.5 w-3.5" /> Used automatically in {main.length || links.length} workflow{(main.length || links.length) === 1 ? "" : "s"}
          </p>
          <p className="text-muted-foreground">
            You don’t need to connect it. Every time one of these saves {an(record)}, your app checks this rule{onlyFills ? " and fills in the values" : view.kind === "decision_table" ? " and fills in the values from the table" : ""}.
          </p>
          <ul className="space-y-1" data-testid="rule-links">
            {(main.length ? main : links).map((l) => (
              <li key={`${l.workflow}:${l.step}`} className="flex items-start gap-2 rounded-md border bg-background px-2 py-1.5" data-link={l.workflow}>
                <Workflow className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
                <span className="min-w-0 flex-1">
                  <WorkflowName id={l.workflow} name={l.name} />
                  <span className="block text-muted-foreground">at “{l.stepName}”, {whenSaid(l, record)}</span>
                </span>
              </li>
            ))}
          </ul>
          {main.length > 0 && also.length > 0 && (
            <p className="text-muted-foreground" data-testid="rule-links-also">
              Also checked in {also.map((l) => l.name).join(", ")}. {also.length === 1 ? "It doesn’t" : "They don’t"} change
              what this rule looks at, so the rule only matters there if the {record} was already wrong.
            </p>
          )}
        </div>
      )}

      {copies.length > 0 && (
        <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-2.5 text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100" data-testid="rule-copies">
          {copies.map((c) => (
            <div key={`${c.workflow}:${c.step}`} className="space-y-1.5">
              <p className="flex items-start gap-1.5">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  <b>{c.name}</b> has its own older check, “{c.stepName}”, that doesn’t match this rule
                  (<code className="rounded bg-amber-100 px-1 dark:bg-amber-900/50">{c.expression}</code>).
                  So that workflow can stop things this rule allows, or let through things it should stop.
                </span>
              </p>
              <Button size="sm" variant="outline" className="h-7 w-full bg-background text-xs" disabled={follow.isPending}
                      onClick={() => follow.mutate({ workflow: c.workflow, step: c.step })}>
                {follow.isPending ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : <CheckCircle2 className="mr-1.5 h-3 w-3" />}
                Use this rule in {c.name} instead
              </Button>
            </div>
          ))}
        </div>
      )}

      {u.steps.length > 0 && (
        <div className="space-y-1">
          <p className="font-medium">Extra check steps</p>
          <ul className="space-y-1">
            {u.steps.map((s) => (
              <li key={s.workflow} className="flex items-center gap-2 rounded-md border bg-background px-2 py-1.5">
                <GitBranch className="h-3.5 w-3.5 text-violet-600" />
                <span className="min-w-0 flex-1">
                  <WorkflowName id={s.workflow} name={s.name} />
                  <span className="block text-muted-foreground">{s.stops ? "stops the workflow if the rule isn’t met" : "carries on either way"}</span>
                </span>
                <button type="button" onClick={() => detach.mutate(s.workflow)} disabled={detach.isPending}
                        aria-label={`Remove the extra check from ${s.name}`} title="Remove this extra check"
                        className="text-muted-foreground hover:text-destructive">
                  <X className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {u.starts.length > 0 && (
        <div className="space-y-1">
          <p className="font-medium">Starts these workflows</p>
          <p className="text-muted-foreground">{u.starts.map((s) => s.name).join(" · ")}</p>
        </div>
      )}

      {!onlyFills && flows.length > 0 && (
        <div className="rounded-lg border bg-muted/30">
          <button type="button" onClick={() => setMore((m) => !m)} aria-expanded={more}
                  className="flex w-full items-center gap-1.5 px-2.5 py-2 text-left font-medium">
            <Plus className="h-3.5 w-3.5" /> Check it earlier in a workflow
            <span className="font-normal text-muted-foreground">(optional)</span>
            <ChevronDown className={cn("ml-auto h-3.5 w-3.5 transition-transform", more && "rotate-180")} />
          </button>
          {more && (
            <div className="space-y-2 border-t p-2.5">
              <p className="text-muted-foreground">
                Only needed if the workflow should check this rule before it gets to saving — for example, before it sends an email.
              </p>
              <select aria-label="Workflow" value={flow} onChange={(e) => { setFlow(e.target.value); setAfter("__start"); setOnStop("stop"); }}
                      className="h-8 w-full rounded-md border bg-background px-2">
                <option value="">Choose a workflow…</option>
                {flows.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
              {flow && (
                <>
                  <label className="block space-y-1">
                    <span className="text-muted-foreground">Where in the workflow</span>
                    <select aria-label="After step" value={after} onChange={(e) => setAfter(e.target.value)}
                            className="h-8 w-full rounded-md border bg-background px-2">
                      <option value="__start">At the start</option>
                      {steps.flatMap((s) => ["condition", "decision", "exclusive_gateway"].includes(String(s.type))
                        // A yes/no step has two ways on: the check goes on one of them.
                        ? [<option key={`${s.key}|then`} value={`${s.key}|then`}>After “{s.name}”, if yes</option>,
                           <option key={`${s.key}|else`} value={`${s.key}|else`}>After “{s.name}”, if no</option>]
                        : [<option key={s.key} value={s.key}>After “{s.name}”</option>])}
                    </select>
                  </label>
                  {canStop ? (
                    <fieldset className="space-y-1">
                      <legend className="text-muted-foreground">If the rule isn’t met</legend>
                      {([["stop", "Stop the workflow and show the rule’s message"], ["continue", "Carry on anyway"]] as const).map(([v, label]) => (
                        <label key={v} className="flex items-center gap-2">
                          <input type="radio" name="on_refusal" checked={onStop === v} onChange={() => setOnStop(v)} /> {label}
                        </label>
                      ))}
                    </fieldset>
                  ) : view.kind === "decision_table" ? (
                    <p className="text-muted-foreground">The values it fills in can be used by the steps after it.</p>
                  ) : null}
                  <Button size="sm" className="w-full" onClick={() => attach.mutate()} disabled={attach.isPending}>
                    {attach.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Plus className="mr-1.5 h-3.5 w-3.5" />}
                    Add the check
                  </Button>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
