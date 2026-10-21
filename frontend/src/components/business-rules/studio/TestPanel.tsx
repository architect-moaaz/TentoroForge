"use client";

// "Test it": a sample save of the record, run by the app's OWN rules engine
// on the server (the rule lab) — the draft among the record's other rules —
// so what it says is what the app will do. Nothing is saved.

import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, CircleSlash, FlaskConical, Loader2, OctagonX, Play, Workflow } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { problemsOf, type CatalogueField } from "@/lib/blueprint-rules";
import { coerceSample, humanField, type FiresOn, type StudioCatalogue, type TestAnswer } from "@/lib/rules-studio";

const SKIP = new Set(["id", "createdAt", "updatedAt", "created_at", "updated_at"]);

export function FieldInput({ f, value, onChange, label }: {
  f: CatalogueField; value: string; onChange: (v: string) => void; label: string;
}) {
  const cls = "h-8 w-full rounded-md border bg-background px-2 text-xs outline-none focus:ring-2 focus:ring-primary/30";
  if (f.type === "enum" && f.enumValues.length) {
    return (
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className={cls}>
        <option value="">— blank —</option>
        {f.enumValues.map((v) => <option key={v} value={v}>{v}</option>)}
      </select>
    );
  }
  if (f.type === "boolean") {
    return (
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className={cls}>
        <option value="">— blank —</option><option value="true">yes</option><option value="false">no</option>
      </select>
    );
  }
  return (
    <input aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}
           type={f.type === "number" ? "number" : f.type === "date" ? "date" : "text"}
           placeholder="blank" className={cls} />
  );
}

export function TestPanel({
  projectId, payload, ruleId, entityId, fields, catalogue, onResult, disabledReason,
}: {
  projectId: string;
  /** The draft as the server takes it; null tests the rules as they are. */
  payload: Record<string, unknown> | null;
  ruleId?: string;
  entityId?: string;
  fields: CatalogueField[];
  catalogue: StudioCatalogue | null;
  onResult?: (r: TestAnswer | null) => void;
  disabledReason?: string;
}) {
  const shown = useMemo(() => fields.filter((f) => !SKIP.has(f.name)), [fields]);
  const [event, setEvent] = useState<FiresOn>("create");
  const [now, setNow] = useState<Record<string, string>>({});
  const [before, setBefore] = useState<Record<string, string>>({});
  const [result, setResult] = useState<TestAnswer | null>(null);
  // A different record (or rule) starts a fresh sample.
  useEffect(() => { setNow({}); setBefore({}); setResult(null); onResult?.(null); }, [entityId]); // eslint-disable-line react-hooks/exhaustive-deps

  const record = (vals: Record<string, string>) =>
    Object.fromEntries(shown.filter((f) => (vals[f.name] ?? "") !== "")
      .map((f) => [f.name, coerceSample(vals[f.name], f.type === "enum" ? "string" : f.type)]));

  const run = useMutation({
    mutationFn: () => api.post<TestAnswer>(`/api/projects/${projectId}/business-rules/test`, {
      rule: payload, rule_id: ruleId, entity: entityId, event,
      record: record(now), previous: event === "update" ? record(before) : null,
    }),
    onSuccess: (r) => { setResult(r); onResult?.(r); },
    onError: (e) => { const r = { ok: false, problems: problemsOf(e) }; setResult(r); onResult?.(r); },
  });

  const flow = (id?: string) => catalogue?.workflows.find((w) => w.id === id)?.name ?? id;

  return (
    <div className="space-y-3" data-testid="test-panel">
      <div className="flex items-center gap-2">
        <FlaskConical className="h-4 w-4 text-violet-600" />
        <p className="text-sm font-semibold">Test it</p>
        <span className="text-[11px] text-muted-foreground">by the app’s own engine · nothing is saved</span>
      </div>
      {disabledReason ? (
        <p className="rounded-md bg-muted/60 p-3 text-xs text-muted-foreground">{disabledReason}</p>
      ) : (
        <>
          <div className="inline-flex rounded-md border p-0.5 text-xs" role="radiogroup" aria-label="Which save">
            {(["create", "update"] as FiresOn[]).map((e) => (
              <button key={e} type="button" role="radio" aria-checked={event === e} onClick={() => setEvent(e)}
                      className={cn("rounded px-2.5 py-1", event === e ? "bg-primary text-primary-foreground" : "hover:bg-muted")}>
                {e === "create" ? "A new record is saved" : "A record is changed"}
              </button>
            ))}
          </div>
          <div className="max-h-[320px] space-y-1.5 overflow-y-auto pr-1">
            {event === "update" && (
              <div className="grid grid-cols-[1fr_1fr_1fr] gap-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                <span>Field</span><span>Before</span><span>Now</span>
              </div>
            )}
            {shown.map((f) => (
              <div key={f.name} className={cn("grid items-center gap-2", event === "update" ? "grid-cols-[1fr_1fr_1fr]" : "grid-cols-[1fr_1.4fr]")}>
                <span className="truncate text-xs" title={f.name}>{humanField(f.name)}{f.required && <span className="text-rose-500"> *</span>}</span>
                {event === "update" && (
                  <FieldInput f={f} label={`${f.name} before`} value={before[f.name] ?? ""} onChange={(v) => setBefore({ ...before, [f.name]: v })} />
                )}
                <FieldInput f={f} label={`${f.name}${event === "update" ? " now" : ""}`} value={now[f.name] ?? ""} onChange={(v) => setNow({ ...now, [f.name]: v })} />
              </div>
            ))}
          </div>
          <Button size="sm" className="w-full" onClick={() => run.mutate()} disabled={run.isPending}>
            {run.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1.5 h-3.5 w-3.5" />}
            Run this save
          </Button>
        </>
      )}

      {result && (
        <div className="space-y-2" data-testid="test-result" data-refused={result.refused ? "yes" : "no"}>
          {result.unavailable && <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-900">{result.unavailable}</p>}
          {!result.refused && result.problems?.length > 0 && !result.trace && (
            <ul className="space-y-1 rounded-md bg-rose-50 p-2 text-xs text-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
              {result.problems.map((p, i) => <li key={i}>{p}</li>)}
            </ul>
          )}
          {result.trace && (
            result.refused ? (
              <div className="rounded-md border border-rose-200 bg-rose-50 p-2.5 dark:border-rose-900 dark:bg-rose-950/40">
                <p className="flex items-center gap-1.5 text-xs font-semibold text-rose-800 dark:text-rose-200"><OctagonX className="h-3.5 w-3.5" /> The app refuses this save</p>
                <ul className="mt-1 space-y-0.5 text-xs text-rose-900 dark:text-rose-200">{(result.errors ?? []).map((e) => <li key={e}>“{e}”</li>)}</ul>
              </div>
            ) : (
              <p className="flex items-center gap-1.5 rounded-md border border-emerald-200 bg-emerald-50 p-2.5 text-xs font-semibold text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">
                <CheckCircle2 className="h-3.5 w-3.5" /> The app saves it
              </p>
            )
          )}
          {result.patches && Object.keys(result.patches).length > 0 && (
            <div className="rounded-md border p-2">
              <p className="mb-1 text-[11px] font-medium text-muted-foreground">The app sets</p>
              <ul className="space-y-0.5 text-xs">
                {Object.entries(result.patches).map(([k, v]) => (
                  <li key={k}><span className="font-medium">{humanField(k)}</span> → <code className="rounded bg-muted px-1">{JSON.stringify(v)}</code></li>
                ))}
              </ul>
            </div>
          )}
          {(result.sideEffects ?? []).length > 0 && (
            <ul className="space-y-0.5 rounded-md border p-2 text-xs">
              {(result.sideEffects ?? []).map((s, i) => (
                <li key={i} className="flex items-center gap-1.5"><Workflow className="h-3 w-3" />
                  {s.type === "trigger_workflow" ? `Starts “${flow(s.workflow)}”` : `Notifies: “${s.message ?? ""}”`}</li>
              ))}
            </ul>
          )}
          {result.trace && result.trace.length > 0 && (
            <details className="rounded-md border p-2 text-xs" open>
              <summary className="cursor-pointer text-[11px] font-medium text-muted-foreground">Why — rule by rule</summary>
              <ul className="mt-1.5 space-y-1">
                {result.trace.map((l) => (
                  <li key={l.id} className={cn("flex items-start gap-1.5", result.focus?.id === l.id && "font-medium")}>
                    {!l.fires ? <CircleSlash className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
                      : (l.kind === "decision_table" ? (l.matched?.length ?? 0) > 0 : l.held)
                        ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-600" />
                        : <CircleSlash className="mt-0.5 h-3 w-3 shrink-0 text-slate-400" />}
                    <span>
                      {result.focus?.id === l.id ? "This rule" : l.name}:{" "}
                      {!l.fires ? "does not fire on this kind of save"
                        : l.kind === "decision_table"
                          ? (l.matched?.length ? `row${l.matched.length > 1 ? "s" : ""} ${l.matched.join(", ")} matched${l.used?.length && l.used.join() !== l.matched.join() ? `, row ${l.used.join(", ")} used` : ""}` : "no row matched")
                          : l.error ? `its condition could not be read — ${l.error}` : l.held ? "its condition holds" : "its condition does not hold"}
                      {l.violation && <span className="block text-amber-700">{l.violation}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
