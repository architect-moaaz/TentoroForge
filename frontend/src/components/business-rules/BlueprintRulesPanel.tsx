"use client";

// The Business Rules tab of an app built from a Living Blueprint.
//
// ONE LIST OF EVERY RULE THE APP HAS, from wherever it came: the person's
// request (the build picked it up), Smith in the chat, or this tab. It reads
// and writes the Blueprint's `businessRules` through
// /api/projects/{id}/business-rules — the record Smith and the build read too —
// and every save is in the running app at once. The list re-reads itself every
// few seconds (faster while a build is writing), so a rule Smith adds appears
// without a reload; an edit of a rule someone else changed meanwhile is refused
// and the person is shown the change.

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle, ChevronLeft, Hammer, Loader2, Plus, RefreshCw, Save, Scale, Sparkles,
  Table2, Trash2, Wand2,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { RuleEditor, emptyDraft, type ConditionActionDraft } from "./RuleEditor";
import { DecisionTableMode, emptyDecisionTable } from "./DecisionTableMode";
import { validateConditionActionRule, validateDecisionTableRule } from "@/lib/business-rule-validation";
import {
  ORIGIN_LABEL, RUNS_LABEL, conditionPayload, editorModel, problemsOf, statementPayload,
  tablePayload, toConditionDraft, toTableDraft,
  type RuleView, type RulesResponse, type StatementDraft, type TableDraft,
} from "@/lib/blueprint-rules";

type Draft =
  | { kind: "condition_action"; ca: ConditionActionDraft; revision?: string }
  | { kind: "decision_table"; dt: TableDraft; revision?: string }
  | { kind: "statement"; st: StatementDraft; revision?: string }
  | { kind: "prerequisite"; view: RuleView; revision?: string };

const key = (projectId: string) => ["project", projectId, "business-rules"] as const;

export function BlueprintRulesPanel({ projectId, initial }: { projectId: string; initial: RulesResponse }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [serverProblems, setServerProblems] = useState<string[]>([]);
  const [stale, setStale] = useState(false);

  const query = useQuery({
    queryKey: key(projectId),
    queryFn: () => api.get<RulesResponse>(`/api/projects/${projectId}/business-rules`),
    initialData: initial,
    // Rules Smith adds, and the build writes, appear without a reload.
    refetchInterval: (q) => ((q.state.data as RulesResponse | undefined)?.building ? 3000 : 6000),
    refetchOnWindowFocus: true,
  });
  const data = query.data ?? initial;
  const model = useMemo(() => editorModel(data.catalogue), [data.catalogue]);
  const live = data.rules;
  const building = data.building;

  // The rule being edited changed elsewhere (Smith, another tab): say so.
  const editingId =
    draft?.kind === "condition_action" ? draft.ca.id : draft?.kind === "decision_table" ? draft.dt.id
      : draft?.kind === "statement" ? draft.st.id : draft?.kind === "prerequisite" ? draft.view.rule.id : undefined;
  useEffect(() => {
    if (!draft || !editingId || !draft.revision) return setStale(false);
    const now = live.find((v) => v.rule.id === editingId);
    setStale(!now || now.revision !== draft.revision);
  }, [live, draft, editingId]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: key(projectId) });

  const openView = (v: RuleView) => {
    setServerProblems([]);
    if (v.kind === "condition_action") setDraft({ kind: "condition_action", ca: toConditionDraft(v, data.catalogue), revision: v.revision });
    else if (v.kind === "decision_table") setDraft({ kind: "decision_table", dt: toTableDraft(v), revision: v.revision });
    else if (v.kind === "prerequisite") setDraft({ kind: "prerequisite", view: v, revision: v.revision });
    else setDraft({ kind: "statement", st: { id: v.rule.id, name: v.rule.name, statement: v.rule.statement, is_active: v.enabled }, revision: v.revision });
  };

  const payloadOf = (d: Draft) => {
    if (d.kind === "condition_action") return conditionPayload(d.ca, model.entityIdByName(d.ca.model_name));
    if (d.kind === "decision_table") return tablePayload(d.dt, model.entityIdByName(d.dt.model));
    if (d.kind === "statement") return statementPayload(d.st);
    return { enabled: d.view.enabled };
  };

  const save = useMutation({
    mutationFn: async (d: Draft) => {
      const body = payloadOf(d);
      const id = editingId;
      if (id) {
        return api.put<{ rule: RuleView }>(`/api/projects/${projectId}/business-rules/${id}`, { ...body, revision: d.revision });
      }
      return api.post<{ rule: RuleView }>(`/api/projects/${projectId}/business-rules`, body);
    },
    onSuccess: (res) => {
      toast.success("Rule saved — it is in force in your app now.");
      setServerProblems([]);
      refresh();
      setDraft(null);
      void res;
    },
    onError: (e) => {
      const problems = problemsOf(e);
      setServerProblems(problems);
      const status = (e as ApiError).status;
      if (status === 409) setStale(true);
      toast.error(problems[0] ?? "The rule could not be saved.");
      if (status === 409 || status === 423) refresh();
    },
  });

  const toggle = useMutation({
    mutationFn: (v: RuleView) =>
      api.patch(`/api/projects/${projectId}/business-rules/${v.rule.id}/enabled`, { enabled: !v.enabled, revision: v.revision }),
    onSuccess: (_r, v) => {
      toast.success(v.enabled ? "Rule switched off — the app no longer applies it." : "Rule switched on — in force now.");
      refresh();
    },
    onError: (e) => {
      toast.error(problemsOf(e)[0]);
      refresh();
    },
  });

  const remove = useMutation({
    mutationFn: (d: { id: string; revision?: string }) =>
      api.delete(`/api/projects/${projectId}/business-rules/${d.id}${d.revision ? `?revision=${d.revision}` : ""}`),
    onSuccess: () => {
      toast.success("Rule removed — the app no longer applies it.");
      refresh();
      setDraft(null);
    },
    onError: (e) => {
      setServerProblems(problemsOf(e));
      toast.error(problemsOf(e)[0]);
      refresh();
    },
  });

  // What the editor would refuse before asking the server, and what the
  // server says as you type (the build's own checks).
  const localProblems = !draft
    ? []
    : draft.kind === "condition_action"
      ? validateConditionActionRule(draft.ca.name, draft.ca.model_name, draft.ca.config).filter(
          // the server reads the text condition; the builder's checks do not apply to it
          (p) => !(draft.ca.expression && /condition/i.test(p)))
      : draft.kind === "decision_table"
        ? [...validateDecisionTableRule(draft.dt.name, draft.dt.table),
           ...(draft.dt.model ? [] : ["Choose the record this table applies to."])]
        : draft.kind === "statement"
          ? [...(draft.st.name.trim() ? [] : ["Give the rule a name."]),
             ...(draft.st.statement.trim() ? [] : ["Say what the rule is, in a sentence."])]
          : [];
  const [checked, setChecked] = useState<{ problems: string[]; runs?: string } | null>(null);
  // Remove asks twice, in place: a browser dialog is blocked in embedded
  // views and answered "no" there, so the button did nothing.
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  useEffect(() => {
    if (!confirmingRemove) return;
    const t = setTimeout(() => setConfirmingRemove(false), 4000);
    return () => clearTimeout(t);
  }, [confirmingRemove]);
  useEffect(() => setConfirmingRemove(false), [editingId]);
  const draftJson = draft ? JSON.stringify(payloadOf(draft)) : "";
  useEffect(() => {
    if (!draft || draft.kind === "prerequisite" || localProblems.length) return setChecked(null);
    const t = setTimeout(() => {
      api
        .post<{ ok: boolean; problems: string[]; runs?: string }>(
          `/api/projects/${projectId}/business-rules/check${editingId ? `?rule_id=${editingId}` : ""}`,
          JSON.parse(draftJson),
        )
        .then((r) => setChecked({ problems: r.problems ?? [], runs: r.runs }))
        .catch(() => setChecked(null));
    }, 500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftJson]);
  const problems = [...localProblems, ...(checked?.problems ?? []), ...serverProblems.filter((p) => !(checked?.problems ?? []).includes(p))];
  const canSave = !!draft && !building && localProblems.length === 0 && (checked?.problems ?? []).length === 0 && !save.isPending;

  // ---- editor ------------------------------------------------------------
  if (draft) {
    const title =
      draft.kind === "condition_action" ? "rule" : draft.kind === "decision_table" ? "decision table"
        : draft.kind === "prerequisite" ? "prerequisite" : "written-down rule";
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b bg-background px-4 py-2.5">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" className="h-7" onClick={() => setDraft(null)}>
              <ChevronLeft className="mr-1 h-4 w-4" /> Rules
            </Button>
            <span className="text-sm font-medium">{editingId ? `Edit ${title} · ${editingId}` : `New ${title}`}</span>
          </div>
          <div className="flex items-center gap-2">
            {editingId && (
              <Button variant="ghost" size="sm" className="h-7 text-rose-500 hover:text-rose-600"
                disabled={remove.isPending || building}
                title="The app stops applying it at once; it stays in the history."
                onClick={() => {
                  if (!confirmingRemove) return setConfirmingRemove(true);
                  setConfirmingRemove(false);
                  remove.mutate({ id: editingId, revision: draft.revision });
                }}>
                <Trash2 className="mr-1 h-3.5 w-3.5" /> {confirmingRemove ? "Click again to remove" : "Remove"}
              </Button>
            )}
            {draft.kind !== "prerequisite" && (
              <Button size="sm" className="h-7" disabled={!canSave} onClick={() => canSave && save.mutate(draft)}>
                {save.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Save className="mr-1 h-3.5 w-3.5" />}
                Save
              </Button>
            )}
          </div>
        </div>
        {building && <BuildingBanner />}
        {stale && (
          <div className="flex items-center justify-between border-b border-sky-200 bg-sky-50 px-4 py-2 text-[11px] text-sky-900 dark:border-sky-900/50 dark:bg-sky-950/30 dark:text-sky-200">
            <span>This rule was changed in the chat or elsewhere since you opened it.</span>
            <Button size="sm" variant="outline" className="h-6 text-[11px]" onClick={() => {
              const now = live.find((v) => v.rule.id === editingId);
              if (now) openView(now);
              else setDraft(null);
            }}>
              <RefreshCw className="mr-1 h-3 w-3" /> Load the latest
            </Button>
          </div>
        )}
        {problems.length > 0 && (
          <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 dark:border-amber-900/50 dark:bg-amber-950/30">
            <ul className="list-inside list-disc space-y-0.5 text-[11px] text-amber-800 dark:text-amber-300">
              {problems.map((p, i) => <li key={i}>{p}</li>)}
            </ul>
          </div>
        )}
        {checked?.runs && problems.length === 0 && (
          <div className="border-b px-4 py-1.5 text-[11px] text-muted-foreground">
            {RUNS_LABEL[checked.runs as keyof typeof RUNS_LABEL] ?? checked.runs}
          </div>
        )}
        <div className="flex-1 overflow-auto p-4">
          {draft.kind === "condition_action" && (
            <RuleEditor
              draft={draft.ca}
              onChange={(ca) => setDraft({ ...draft, ca })}
              models={model.models}
              getFields={model.getFields}
              enumValuesForType={model.enumValuesForType}
              hasModel={model.hasModel}
              workflows={data.catalogue?.workflows ?? []}
              withStatement
            />
          )}
          {draft.kind === "decision_table" && (
            <div className="space-y-3">
              <DecisionTableMode
                name={draft.dt.name}
                onNameChange={(name) => setDraft({ ...draft, dt: { ...draft.dt, name } })}
                table={draft.dt.table}
                onTableChange={(table) => setDraft({ ...draft, dt: { ...draft.dt, table } })}
                appModel={null}
                models={model.models}
                getFields={model.getFields}
                enumValuesForType={model.enumValuesForType}
                boundModel={draft.dt.model}
                onBoundModelChange={(m) => setDraft({ ...draft, dt: { ...draft.dt, model: m } })}
              />
              <div className="flex items-center gap-2">
                <Switch checked={draft.dt.is_active} onCheckedChange={(is_active) => setDraft({ ...draft, dt: { ...draft.dt, is_active } })} />
                <Label className="text-xs">{draft.dt.is_active ? "On" : "Off"}</Label>
              </div>
            </div>
          )}
          {draft.kind === "statement" && (
            <div className="max-w-2xl space-y-3">
              <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  This rule is written down but nothing in the app enforces it yet. Make it enforceable to choose
                  its record, when it applies and what it does — or ask Smith in the chat to do it.
                </span>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Name</Label>
                <Input className="h-8 text-sm" value={draft.st.name}
                  onChange={(e) => setDraft({ ...draft, st: { ...draft.st, name: e.target.value } })} />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">What the rule says</Label>
                <Textarea className="min-h-[70px] text-sm" value={draft.st.statement}
                  onChange={(e) => setDraft({ ...draft, st: { ...draft.st, statement: e.target.value } })} />
              </div>
              <Button size="sm" variant="outline" className="h-7" onClick={() => {
                const ca = emptyDraft();
                setDraft({
                  kind: "condition_action",
                  revision: draft.revision,
                  ca: { ...ca, id: draft.st.id, name: draft.st.name, statement: draft.st.statement,
                        is_active: draft.st.is_active, model_name: model.models[0] ?? null },
                });
              }}>
                <Wand2 className="mr-1 h-3.5 w-3.5" /> Make it enforceable
              </Button>
            </div>
          )}
          {draft.kind === "prerequisite" && <PrerequisiteView view={draft.view} />}
        </div>
      </div>
    );
  }

  // ---- list --------------------------------------------------------------
  const enforced = live.filter((v) => v.enabled && v.enforced);
  const written = live.filter((v) => v.enabled && !v.enforced);
  const off = live.filter((v) => !v.enabled);
  const newRule = () => {
    setServerProblems([]);
    setDraft({ kind: "condition_action", ca: { ...emptyDraft(), model_name: model.models[0] ?? null, statement: "" } });
  };
  const newTable = () => {
    setServerProblems([]);
    setDraft({ kind: "decision_table", dt: { name: "", statement: "", is_active: true, model: model.models[0] ?? null, table: emptyDecisionTable() } });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 border-b bg-background px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <Scale className="h-4 w-4 shrink-0 text-indigo-500" />
          <span className="shrink-0 text-sm font-medium">Business Rules</span>
          <span className="hidden min-w-0 truncate text-xs text-muted-foreground xl:inline">
            Every rule of your app — from your request, Smith, and here. Changes apply to the app at once.
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="outline" size="sm" className="h-7" onClick={newTable} disabled={building || !model.hasModel}>
            <Table2 className="mr-1 h-3.5 w-3.5" /> Decision table
          </Button>
          <Button size="sm" className="h-7" onClick={newRule} disabled={building || !model.hasModel}>
            <Plus className="mr-1 h-3.5 w-3.5" /> New rule
          </Button>
        </div>
      </div>
      {building && <BuildingBanner />}
      <div className="flex-1 overflow-auto p-4">
        {(data.planned ?? []).length > 0 && (
          <section className="mb-5">
            <div className="mb-1.5 flex items-baseline gap-2">
              <h3 className="text-xs font-semibold text-indigo-700 dark:text-indigo-300">
                Asked for — enforced once the app is built <span className="font-normal text-muted-foreground">· {(data.planned ?? []).length}</span>
              </h3>
              <span className="text-[11px] text-muted-foreground">From what you told Smith.</span>
            </div>
            <div className="space-y-1.5">
              {(data.planned ?? []).map((p) => (
                <div key={p.id} className="flex items-start gap-2 rounded-md border border-dashed bg-card px-3 py-2">
                  <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-500" />
                  <div className="min-w-0">
                    <p className="text-[12px]">{p.description}</p>
                    <p className="text-[10px] text-muted-foreground">{p.id} · From your request</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
        {live.length === 0 && (data.planned ?? []).length > 0 ? null : live.length === 0 ? (
          <div className="mx-auto max-w-md rounded-lg border border-dashed py-12 text-center">
            <Scale className="mx-auto h-8 w-8 text-muted-foreground/50" />
            <p className="mt-3 text-sm font-medium">No business rules yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {model.hasModel
                ? "Add one here (“when amount > 5000, require a manager’s note”), or tell Smith in the chat — it appears here either way."
                : "Rules apply to your app’s records. Once Smith has worked out what your app is made of, add them here or in the chat."}
            </p>
            {model.hasModel && (
              <div className="mt-4 flex justify-center gap-2">
                <Button size="sm" className="h-7" onClick={newRule} disabled={building}>
                  <Plus className="mr-1 h-3.5 w-3.5" /> New rule
                </Button>
                <Button variant="outline" size="sm" className="h-7" onClick={newTable} disabled={building}>
                  <Table2 className="mr-1 h-3.5 w-3.5" /> Decision table
                </Button>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-5">
            <Group title="Enforced in your app" hint="Applied whenever these records are saved or filled in." views={enforced}
              onOpen={openView} onToggle={(v) => toggle.mutate(v)} busy={toggle.isPending || building} />
            <Group title="Written down — not enforced yet" hint="Open one to make it enforceable, or ask Smith."
              tone="amber" views={written} onOpen={openView} onToggle={(v) => toggle.mutate(v)} busy={toggle.isPending || building} />
            <Group title="Switched off" hint="Kept, but the app does not apply them." tone="muted" views={off}
              onOpen={openView} onToggle={(v) => toggle.mutate(v)} busy={toggle.isPending || building} />
          </div>
        )}
      </div>
    </div>
  );
}

function BuildingBanner() {
  return (
    <div className="flex items-center gap-2 border-b border-indigo-200 bg-indigo-50 px-4 py-2 text-[11px] text-indigo-900 dark:border-indigo-900/50 dark:bg-indigo-950/30 dark:text-indigo-200">
      <Hammer className="h-3.5 w-3.5" />
      Forge is building this app. Rules are read-only until the build finishes — new rules it writes appear here as they are made.
    </div>
  );
}

function Group({
  title, hint, views, onOpen, onToggle, busy, tone,
}: {
  title: string; hint: string; views: RuleView[]; onOpen: (v: RuleView) => void;
  onToggle: (v: RuleView) => void; busy: boolean; tone?: "amber" | "muted";
}) {
  if (!views.length) return null;
  return (
    <section>
      <div className="mb-1.5 flex items-baseline gap-2">
        <h3 className={`text-xs font-semibold ${tone === "amber" ? "text-amber-700 dark:text-amber-400" : tone === "muted" ? "text-muted-foreground" : ""}`}>
          {title} <span className="font-normal text-muted-foreground">· {views.length}</span>
        </h3>
        <span className="text-[11px] text-muted-foreground">{hint}</span>
      </div>
      <div className="space-y-1.5">
        {views.map((v) => <Row key={v.rule.id} view={v} onOpen={() => onOpen(v)} onToggle={() => onToggle(v)} busy={busy} />)}
      </div>
    </section>
  );
}

function Row({ view, onOpen, onToggle, busy }: { view: RuleView; onOpen: () => void; onToggle: () => void; busy: boolean }) {
  const r = view.rule;
  const Icon = view.kind === "decision_table" ? Table2 : view.origin === "brief" ? Sparkles : Scale;
  const where = view.kind === "prerequisite"
    ? `Checked before ${view.gates.map((g) => g.name ?? g.id).join(", ") || "its workflows"}`
    : RUNS_LABEL[view.runs];
  return (
    <div className="flex items-start gap-3 rounded-md border bg-card px-3 py-2.5 transition-colors hover:bg-accent/40">
      <button type="button" className="min-w-0 flex-1 text-left" onClick={onOpen}>
        <div className="flex flex-wrap items-center gap-1.5">
          <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate text-sm font-medium">{r.name}</span>
          <span className="font-mono text-[10px] text-muted-foreground">{r.id}</span>
          <Badge variant="outline" className="h-4 px-1 text-[10px] font-normal">{ORIGIN_LABEL[view.origin]}</Badge>
          {view.entityName && <Badge variant="secondary" className="h-4 px-1 text-[10px] font-normal">{view.entityName}</Badge>}
        </div>
        <p className="mt-0.5 line-clamp-2 pl-5 text-[12px] text-muted-foreground">{r.statement}</p>
        <p className={`mt-0.5 pl-5 text-[11px] ${view.enforced ? "text-emerald-700 dark:text-emerald-400" : "text-amber-700 dark:text-amber-400"}`}>
          {view.enabled ? where : "Switched off"}
          {view.requirements.length > 0 && (
            <span className="text-muted-foreground"> · for {view.requirements.map((q) => q.id).join(", ")}</span>
          )}
        </p>
      </button>
      <Switch checked={view.enabled} disabled={busy} onCheckedChange={onToggle}
        aria-label={view.enabled ? `Switch off ${r.name}` : `Switch on ${r.name}`} />
    </div>
  );
}

function PrerequisiteView({ view }: { view: RuleView }) {
  const r = view.rule;
  return (
    <div className="max-w-2xl space-y-2 text-sm">
      <p className="font-medium">{r.name}</p>
      <p className="text-muted-foreground">{r.statement}</p>
      <p className="text-xs">
        Checked before: {view.gates.map((g) => `${g.name ?? g.id} (${g.id})`).join(", ") || "—"}
      </p>
      {r.message && <p className="text-xs">The person is told: “{r.message}”</p>}
      <p className="text-[11px] text-muted-foreground">
        A prerequisite gates workflows. Switch it off or remove it here; to change what it requires, ask Smith in the chat.
      </p>
    </div>
  );
}
