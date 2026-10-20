"use client";

// THE BUSINESS RULES STUDIO — every rule of the app, from wherever it came
// (the person's request, Smith, this tab), in one list; and an editor that is
// Drools' guided rules and decision tables in plain words:
//   · a when → then rule, typed by the record's fields;
//   · a decision table, checked cell by cell by the app's own engine;
//   · a written rule, for what the app cannot check on a save (or an app that
//     keeps no records), with "Ask Smith to build it in";
// each tested by the app's own engine before it is saved, and placed in the
// workflows it should run in. The Blueprint's `businessRules` is the record:
// the build and Smith read it too, and every save is in the running app at once.

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle, BookText, ChevronDown, FileText, GitBranch, Hammer, Lightbulb, Loader2, MessageSquare,
  Plus, RefreshCw, Save, Scale, Search, ShieldCheck, Table2, Trash2, Wand2, X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { askSmith } from "@/lib/ask-smith";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  ORIGIN_LABEL, RUNS_LABEL, conditionPayload, editorModel, problemsOf, toConditionDraft,
  type RulesResponse,
} from "@/lib/blueprint-rules";
import {
  blankRuleOn, emptyTable, ruleSentence, tableFromStored, tableToStored,
  type CheckAnswer, type FiresOn, type StudioCatalogue, type StudioView, type TableState, type TestAnswer,
} from "@/lib/rules-studio";
import { WhenThenEditor, emptyDraft, type ConditionActionDraft } from "./WhenThenEditor";
import { TableEditor } from "./TableEditor";
import { TestPanel } from "./TestPanel";
import { WorkflowsPanel } from "./WorkflowsPanel";

type Draft = { id?: string; revision?: string } & (
  | { kind: "condition_action"; ca: ConditionActionDraft; on: FiresOn[] }
  | { kind: "decision_table"; name: string; statement: string; model: string | null; enabled: boolean;
      table: TableState; on: FiresOn[] }
  | { kind: "statement"; name: string; statement: string; enabled: boolean }
  | { kind: "prerequisite"; view: StudioView }
);

const BUSY_SAID: Record<string, string> = {
  building: "Forge is building this app. Rules are read-only until the build finishes — rules it writes appear here as they are made.",
  checking: "Forge is checking the app it just built and fixing what it finds. Rules are read-only until that finishes.",
  smith: "Smith is working on this app. Rules are read-only until Smith finishes — any rule Smith changes appears here.",
};

const KIND_ICON = { condition_action: Scale, decision_table: Table2, statement: BookText, prerequisite: ShieldCheck };
const key = (projectId: string) => ["project", projectId, "business-rules"] as const;

export function RulesStudio({ projectId, initial }: { projectId: string; initial: RulesResponse }) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: key(projectId),
    queryFn: () => api.get<RulesResponse>(`/api/projects/${projectId}/business-rules`),
    initialData: initial,
    refetchInterval: (q) => ((q.state.data as RulesResponse | undefined)?.building ? 3000 : 8000),
    refetchOnWindowFocus: true,
  });
  const data = query.data ?? initial;
  const catalogue = data.catalogue as StudioCatalogue | null;
  const views = data.rules as StudioView[];
  const model = useMemo(() => editorModel(data.catalogue), [data.catalogue]);
  const building = data.building;
  const hasRecords = model.hasModel;

  const [q, setQ] = useState("");
  const [record, setRecord] = useState<string>("all");
  const [draft, setDraft] = useState<Draft | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: key(projectId) });

  const toggle = useMutation({
    mutationFn: (v: StudioView) =>
      api.patch(`/api/projects/${projectId}/business-rules/${v.rule.id}/enabled`, { enabled: !v.enabled, revision: v.revision }),
    onSuccess: (_r, v) => { toast.success(v.enabled ? "Switched off — the app no longer applies it." : "Switched on — in force in your app now."); refresh(); },
    onError: (e) => { toast.error(problemsOf(e)[0]); refresh(); },
  });

  const shown = views.filter((v) => {
    if (record !== "all" && v.entityName !== record) return false;
    if (!q.trim()) return true;
    const hay = `${v.rule.name} ${v.rule.statement} ${v.entityName ?? ""} ${v.rule.id}`.toLowerCase();
    return hay.includes(q.trim().toLowerCase());
  });
  const enforced = shown.filter((v) => v.enabled && v.enforced);
  const written = shown.filter((v) => v.enabled && !v.enforced);
  const off = shown.filter((v) => !v.enabled);

  const open = (v: StudioView) => {
    const base = { id: v.rule.id, revision: v.revision };
    if (v.kind === "condition_action") {
      setDraft({ ...base, kind: "condition_action", ca: toConditionDraft(v, data.catalogue), on: blankRuleOn(v.rule.on) });
    } else if (v.kind === "decision_table") {
      setDraft({ ...base, kind: "decision_table", name: v.rule.name, statement: v.rule.statement ?? "", model: v.entityName,
                 enabled: v.enabled, table: tableFromStored(v.rule.table), on: blankRuleOn(v.rule.on) });
    } else if (v.kind === "prerequisite") {
      setDraft({ ...base, kind: "prerequisite", view: v });
    } else {
      setDraft({ ...base, kind: "statement", name: v.rule.name, statement: v.rule.statement ?? "", enabled: v.enabled });
    }
  };
  const first = model.models[0] ?? null;
  const create = (kind: "condition_action" | "decision_table" | "statement") => {
    if (kind === "condition_action") setDraft({ kind, ca: emptyDraft(first), on: ["create", "update"] });
    else if (kind === "decision_table") setDraft({ kind, name: "", statement: "", model: first, enabled: true, table: emptyTable(), on: ["create", "update"] });
    else setDraft({ kind, name: "", statement: "", enabled: true });
  };

  return (
    <div className="flex h-full flex-col" data-testid="rules-studio">
      <div className="border-b px-6 py-4">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="flex items-center gap-2 text-lg font-semibold"><Scale className="h-5 w-5 text-violet-600" /> Business rules</h2>
            <p className="text-sm text-muted-foreground">
              What your app checks and works out — every rule from your request, from Smith and from here. A change is in your app the moment you save it.
            </p>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button disabled={building} data-testid="new-rule"><Plus className="mr-1.5 h-4 w-4" /> New rule <ChevronDown className="ml-1 h-3.5 w-3.5" /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-80">
              <NewItem icon={Scale} title="When → then rule" disabled={!hasRecords}
                       says={hasRecords ? "Refuse a save, set or require a value, start a workflow — when a condition holds." : "Needs a record this app keeps."}
                       onSelect={() => create("condition_action")} />
              <NewItem icon={Table2} title="Decision table" disabled={!hasRecords}
                       says={hasRecords ? "Work out a value from a few fields, one row per case." : "Needs a record this app keeps."}
                       onSelect={() => create("decision_table")} />
              <NewItem icon={BookText} title="Written rule" says="A rule in words — for the screens, or anything a save cannot check." onSelect={() => create("statement")} />
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="relative w-64">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a rule…" className="h-8 pl-8 text-sm" />
          </div>
          {model.models.length > 1 && (
            <select aria-label="Record" value={record} onChange={(e) => setRecord(e.target.value)} className="h-8 rounded-md border bg-background px-2 text-sm">
              <option value="all">Every record</option>
              {model.models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          )}
          <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
            <span><b className="text-foreground">{views.filter((v) => v.enabled && v.enforced).length}</b> enforced</span>
            <span><b className="text-foreground">{views.filter((v) => v.enabled && !v.enforced).length}</b> written</span>
            <span><b className="text-foreground">{views.filter((v) => !v.enabled).length}</b> off</span>
            <button type="button" onClick={refresh} aria-label="Reload" className="hover:text-foreground"><RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /></button>
          </div>
        </div>
      </div>

      {building && (
        <div className="flex items-center gap-2 border-b border-indigo-200 bg-indigo-50 px-6 py-2 text-xs text-indigo-900 dark:border-indigo-900/50 dark:bg-indigo-950/30 dark:text-indigo-200">
          <Hammer className="h-3.5 w-3.5" /> {BUSY_SAID[data.busy ?? "building"] ?? BUSY_SAID.building}
        </div>
      )}

      <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
        {!hasRecords && (
          <div className="flex gap-3 rounded-xl border border-violet-200 bg-violet-50/60 p-4 text-sm dark:border-violet-900 dark:bg-violet-950/20" data-testid="no-records">
            <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-violet-600" />
            <div className="space-y-1">
              <p className="font-medium">This app keeps no records, so there is nothing for a rule to check on a save.</p>
              <p className="text-muted-foreground">
                Its rules are about how its screens behave. They are written here so nothing you asked for is lost —
                and Smith builds each one into the app’s screens when you ask. Open a rule and choose <b>Ask Smith to build it in</b>.
              </p>
            </div>
          </div>
        )}

        {(data.planned ?? []).length > 0 && (
          <section className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 dark:border-amber-900 dark:bg-amber-950/20">
            <p className="text-sm font-medium">You asked for these — no rule covers them yet</p>
            <ul className="mt-2 space-y-1.5">
              {(data.planned ?? []).map((p) => (
                <li key={p.id} className="flex items-start gap-2 text-sm">
                  <span className="flex-1">{p.description}</span>
                  <Button size="sm" variant="outline" className="h-7 text-xs"
                          onClick={() => askSmith(projectId, `Make this a business rule of the app, enforced: “${p.description}”`)}>
                    <MessageSquare className="mr-1 h-3 w-3" /> Ask Smith
                  </Button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {views.length === 0 ? (
          <div className="mx-auto max-w-lg rounded-xl border border-dashed p-10 text-center">
            <Scale className="mx-auto h-8 w-8 text-muted-foreground" />
            <p className="mt-3 font-medium">No rules yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Rules are what your app checks and works out on its own: “an expense above 5000 needs a manager’s note”,
              “the approver is the CFO above 10,000”. Make one from <b>New rule</b>, or tell Smith in the chat.
            </p>
          </div>
        ) : shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">No rule matches.</p>
        ) : (
          <>
            <Group title="Enforced" hint="The app applies these." views={enforced} catalogue={catalogue} onOpen={open} onToggle={(v) => toggle.mutate(v)} busy={building} />
            <Group title="Written down — not checked by the app" hint={hasRecords ? "Open one to make it enforceable, or ask Smith." : "Ask Smith to build them into the app."} tone="amber"
                   views={written} catalogue={catalogue} onOpen={open} onToggle={(v) => toggle.mutate(v)} busy={building} />
            <Group title="Switched off" hint="Kept, but the app does not apply them." tone="muted" views={off} catalogue={catalogue} onOpen={open} onToggle={(v) => toggle.mutate(v)} busy={building} />
          </>
        )}
      </div>

      <RuleSheet projectId={projectId} draft={draft} setDraft={setDraft} views={views} catalogue={catalogue}
                 model={model} building={building} onSaved={refresh} />
    </div>
  );
}

function NewItem({ icon: Icon, title, says, onSelect, disabled }: {
  icon: typeof Scale; title: string; says: string; onSelect: () => void; disabled?: boolean;
}) {
  return (
    <DropdownMenuItem onSelect={onSelect} disabled={disabled} className="items-start gap-3 py-2">
      <Icon className="mt-0.5 h-4 w-4 text-violet-600" />
      <span>
        <span className="block text-sm font-medium">{title}</span>
        <span className="block text-xs text-muted-foreground">{says}</span>
      </span>
    </DropdownMenuItem>
  );
}

function Group({ title, hint, views, catalogue, onOpen, onToggle, busy, tone }: {
  title: string; hint: string; views: StudioView[]; catalogue: StudioCatalogue | null;
  onOpen: (v: StudioView) => void; onToggle: (v: StudioView) => void; busy: boolean; tone?: "amber" | "muted";
}) {
  if (!views.length) return null;
  return (
    <section>
      <div className="mb-2 flex items-baseline gap-2">
        <h3 className={cn("text-sm font-semibold", tone === "amber" && "text-amber-700 dark:text-amber-400", tone === "muted" && "text-muted-foreground")}>
          {title} <span className="font-normal text-muted-foreground">· {views.length}</span>
        </h3>
        <span className="text-xs text-muted-foreground">{hint}</span>
      </div>
      <div className="grid gap-2">
        {views.map((v) => <RuleCard key={v.rule.id} view={v} catalogue={catalogue} onOpen={() => onOpen(v)} onToggle={() => onToggle(v)} busy={busy} />)}
      </div>
    </section>
  );
}

function RuleCard({ view, catalogue, onOpen, onToggle, busy }: {
  view: StudioView; catalogue: StudioCatalogue | null; onOpen: () => void; onToggle: () => void; busy: boolean;
}) {
  const Icon = KIND_ICON[view.kind] ?? Scale;
  const u = view.usages;
  return (
    <div className={cn("group flex items-start gap-3 rounded-xl border bg-card p-3.5 transition-shadow hover:shadow-sm", !view.enabled && "opacity-70")}
         data-rule={view.rule.id}>
      <button type="button" onClick={onOpen} className="flex min-w-0 flex-1 items-start gap-3 text-left">
        <span className={cn("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                            view.kind === "decision_table" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                              : view.kind === "statement" ? "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                              : "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300")}>
          <Icon className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="font-medium group-hover:underline">{view.rule.name}</span>
            <code className="text-[10px] text-muted-foreground">{view.rule.id}</code>
            {view.entityName && <Badge variant="secondary" className="text-[10px]">{view.entityName}</Badge>}
            <Badge variant="outline" className="text-[10px]">{ORIGIN_LABEL[view.origin] ?? view.origin}</Badge>
          </span>
          <span className="mt-1 block text-sm text-muted-foreground">{ruleSentence(view, catalogue)}</span>
          <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
            <span className={view.enforced && view.enabled ? "text-emerald-700 dark:text-emerald-400" : "text-amber-700 dark:text-amber-400"}>
              {view.enabled ? RUNS_LABEL[view.runs] : "Switched off"}
            </span>
            {(u?.steps ?? []).map((s) => (
              <span key={s.workflow} className="inline-flex items-center gap-1 text-violet-700 dark:text-violet-300"><GitBranch className="h-3 w-3" /> step in {s.name}</span>
            ))}
            {(u?.saves.length ?? 0) > 0 && view.enforced && (
              <span className="text-muted-foreground">checked in {u!.saves.length} workflow{u!.saves.length === 1 ? "" : "s"}</span>
            )}
            {view.requirements.length > 0 && <span className="text-muted-foreground">for {view.requirements.map((r) => r.id).join(", ")}</span>}
          </span>
        </span>
      </button>
      <Switch checked={view.enabled} onCheckedChange={onToggle} disabled={busy} aria-label={view.enabled ? `Switch off ${view.rule.name}` : `Switch on ${view.rule.name}`} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// The editor
// ---------------------------------------------------------------------------

function RuleSheet({ projectId, draft, setDraft, views, catalogue, model, building, onSaved }: {
  projectId: string; draft: Draft | null; setDraft: (d: Draft | null) => void; views: StudioView[];
  catalogue: StudioCatalogue | null; model: ReturnType<typeof editorModel>; building: boolean; onSaved: () => void;
}) {
  const [check, setCheck] = useState<CheckAnswer | null>(null);
  const [saveProblems, setSaveProblems] = useState<string[]>([]);
  const [test, setTest] = useState<TestAnswer | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const saved = draft?.id ? views.find((v) => v.rule.id === draft.id) ?? null : null;
  const stale = !!(draft?.id && draft.revision && saved && saved.revision !== draft.revision);
  const gone = !!(draft?.id && !saved);

  useEffect(() => { setCheck(null); setSaveProblems([]); setTest(null); setConfirmDelete(false); }, [draft?.id, draft?.kind]);

  const payload = useMemo((): Record<string, unknown> | null => {
    if (!draft) return null;
    if (draft.kind === "condition_action") {
      return { ...conditionPayload(draft.ca, model.entityIdByName(draft.ca.model_name)), on: draft.on };
    }
    if (draft.kind === "decision_table") {
      return { kind: "decision_table", name: draft.name.trim(), statement: draft.statement.trim(),
               entity: model.entityIdByName(draft.model), enabled: draft.enabled, table: tableToStored(draft.table), on: draft.on };
    }
    if (draft.kind === "statement") {
      return { kind: "statement", name: draft.name.trim(), statement: draft.statement.trim(), enabled: draft.enabled };
    }
    return { enabled: draft.view.enabled };
  }, [draft, model]);

  // Live: checked as the person edits — by the server, with the app's engine.
  const seq = useRef(0);
  useEffect(() => {
    if (!draft || !payload || draft.kind === "prerequisite") return;
    const n = ++seq.current;
    const t = setTimeout(() => {
      api.post<CheckAnswer>(`/api/projects/${projectId}/business-rules/check${draft.id ? `?rule_id=${encodeURIComponent(draft.id)}` : ""}`, payload)
        .then((r) => { if (n === seq.current) setCheck(r); })
        .catch(() => { if (n === seq.current) setCheck(null); });
    }, 450);
    return () => clearTimeout(t);
  }, [payload, projectId, draft]);

  const save = useMutation({
    mutationFn: () => draft?.id
      ? api.put(`/api/projects/${projectId}/business-rules/${draft.id}`, { ...payload, revision: draft.revision })
      : api.post(`/api/projects/${projectId}/business-rules`, payload),
    onSuccess: () => { toast.success("Saved — in force in your app now."); onSaved(); setDraft(null); },
    onError: (e) => {
      setSaveProblems(problemsOf(e));
      toast.error(problemsOf(e)[0] ?? "The rule could not be saved.");
      if ([409, 423].includes((e as ApiError).status)) onSaved();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/api/projects/${projectId}/business-rules/${draft!.id}${draft!.revision ? `?revision=${encodeURIComponent(draft!.revision)}` : ""}`),
    onSuccess: () => { toast.success("Rule removed — the app no longer applies it."); onSaved(); setDraft(null); },
    onError: (e) => toast.error(problemsOf(e)[0]),
  });

  if (!draft) return null;
  const nameOf = draft.kind === "condition_action" ? draft.ca.name : draft.kind === "prerequisite" ? draft.view.rule.name : draft.name;
  const setName = (name: string) => {
    if (draft.kind === "condition_action") setDraft({ ...draft, ca: { ...draft.ca, name } });
    else if (draft.kind !== "prerequisite") setDraft({ ...draft, name } as Draft);
  };
  const enabled = draft.kind === "condition_action" ? draft.ca.is_active : draft.kind === "prerequisite" ? draft.view.enabled : draft.enabled;
  const setEnabled = (on: boolean) => {
    if (draft.kind === "condition_action") setDraft({ ...draft, ca: { ...draft.ca, is_active: on } });
    else if (draft.kind === "prerequisite") setDraft({ ...draft, view: { ...draft.view, enabled: on } });
    else setDraft({ ...draft, enabled: on } as Draft);
  };
  const problems = saveProblems.length ? saveProblems : check?.problems ?? [];
  const entityName = draft.kind === "condition_action" ? draft.ca.model_name : draft.kind === "decision_table" ? draft.model : null;
  const fields = (catalogue?.entities.find((e) => e.name === entityName)?.fields) ?? [];
  const asView = { ...(saved ?? {}), kind: draft.kind, entityName, rule: { ...(saved?.rule ?? {}), ...(payload ?? {}) } } as StudioView;
  const sentence = draft.kind === "condition_action" || draft.kind === "decision_table" ? ruleSentence(asView, catalogue) : null;
  const canSave = !building && !stale && !gone && nameOf.trim().length > 0 && (check ? check.ok : true) && !save.isPending;
  const Icon = KIND_ICON[draft.kind] ?? Scale;

  return (
    <Sheet open={!!draft} onOpenChange={(o) => !o && setDraft(null)}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-[1180px]" data-testid="rule-sheet">
        <div className="flex items-center gap-3 border-b px-5 py-3">
          <Icon className="h-5 w-5 text-violet-600" />
          <div className="min-w-0 flex-1">
            <SheetTitle className="sr-only">{nameOf || "New rule"}</SheetTitle>
            <SheetDescription className="sr-only">Edit a business rule</SheetDescription>
            <input value={nameOf} onChange={(e) => setName(e.target.value)} disabled={draft.kind === "prerequisite"}
                   placeholder={draft.kind === "decision_table" ? "Name the table — e.g. Approver by amount" : "Name the rule — e.g. Big expenses need a note"}
                   aria-label="Rule name" className="w-full bg-transparent text-lg font-semibold outline-none placeholder:text-muted-foreground/60" />
            <p className="text-xs text-muted-foreground">
              {{ condition_action: "When → then rule", decision_table: "Decision table", statement: "Written rule", prerequisite: "Prerequisite — set up by Smith" }[draft.kind]}
              {draft.id && <> · <code>{draft.id}</code></>}
            </p>
          </div>
          <label className="flex items-center gap-2 text-xs">
            <Switch checked={enabled} onCheckedChange={setEnabled} disabled={building} aria-label="On or off" /> {enabled ? "On" : "Off"}
          </label>
          {draft.id && draft.kind !== "prerequisite" && (
            confirmDelete ? (
              <Button variant="destructive" size="sm" onClick={() => remove.mutate()} disabled={remove.isPending || building}>Remove it</Button>
            ) : (
              <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)} disabled={building} aria-label="Remove rule"><Trash2 className="h-4 w-4" /></Button>
            )
          )}
          <Button variant="ghost" size="sm" onClick={() => setDraft(null)}><X className="mr-1 h-4 w-4" /> Close</Button>
          <Button size="sm" onClick={() => save.mutate()} disabled={!canSave} data-testid="save-rule">
            {save.isPending ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />} Save
          </Button>
        </div>

        {(stale || gone) && (
          <div className="flex items-center gap-2 border-b bg-amber-50 px-5 py-2 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
            <AlertTriangle className="h-3.5 w-3.5" />
            {gone ? "This rule was removed while you had it open." : "This rule was changed (by Smith or someone else) while you had it open."}
            {saved && <Button size="sm" variant="outline" className="ml-auto h-7 text-xs" onClick={() => setDraft(null)}>Close and reopen it</Button>}
          </div>
        )}

        <div className="grid h-[calc(100%-57px)] grid-cols-1 overflow-hidden lg:grid-cols-[1fr_380px]">
          <div className="space-y-4 overflow-y-auto p-5">
            {sentence && (
              <p className="rounded-lg bg-muted/50 px-3 py-2 text-sm" data-testid="reads-as">
                <span className="mr-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Reads as</span>{sentence}
              </p>
            )}
            {problems.length > 0 && (
              <ul className="space-y-1 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200" data-testid="problems">
                {problems.map((p) => <li key={p} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{p}</li>)}
              </ul>
            )}
            {(check?.advice ?? []).length > 0 && (
              <ul className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                {check!.advice!.map((a) => <li key={a} className="flex gap-1.5"><Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0" />{a}</li>)}
              </ul>
            )}

            {draft.kind === "condition_action" && (
              <WhenThenEditor draft={draft.ca} onChange={(ca) => setDraft({ ...draft, ca })} models={model.models}
                              getFields={model.getFields} enumValuesForType={model.enumValuesForType}
                              workflows={catalogue?.workflows ?? []} on={draft.on} onOn={(on) => setDraft({ ...draft, on })} disabled={building} />
            )}
            {draft.kind === "decision_table" && (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span>When a</span>
                  <select aria-label="Record" value={draft.model ?? ""} disabled={building || draft.table.inputs.length + draft.table.outputs.length > 0}
                          title={draft.table.inputs.length ? "Remove the columns to change the record" : undefined}
                          onChange={(e) => setDraft({ ...draft, model: e.target.value })}
                          className="h-8 rounded-md border bg-background px-2 font-medium">
                    {model.models.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                  <span>is</span>
                  {(["create", "update"] as FiresOn[]).map((e) => (
                    <button key={e} type="button" aria-pressed={draft.on.includes(e)} disabled={building}
                            onClick={() => { const n = draft.on.includes(e) ? draft.on.filter((x) => x !== e) : [...draft.on, e]; if (n.length) setDraft({ ...draft, on: n }); }}
                            className={cn("rounded-full border px-3 py-1 text-xs font-medium", draft.on.includes(e) ? "border-sky-600 bg-sky-600 text-white" : "hover:bg-muted")}>
                      {e === "create" ? "created" : "changed"}
                    </button>
                  ))}
                  <span>— on every such save, the table sets the fields on its right.</span>
                </div>
                <TableEditor value={draft.table} onChange={(table) => setDraft({ ...draft, table })} fields={fields}
                             findings={check?.findings ?? []} matched={test?.focus?.matched} used={test?.focus?.used} disabled={building} />
                <label className="block space-y-1">
                  <span className="text-xs font-medium">In a sentence <span className="font-normal text-muted-foreground">(left empty, Forge writes it)</span></span>
                  <Textarea className="min-h-[48px] text-sm" value={draft.statement} disabled={building}
                            placeholder="The approver is set from the amount: a manager up to 5000, the CFO above."
                            onChange={(e) => setDraft({ ...draft, statement: e.target.value })} />
                </label>
              </div>
            )}
            {draft.kind === "statement" && (
              <div className="space-y-3">
                <Textarea className="min-h-[120px] text-base" value={draft.statement} disabled={building} aria-label="The rule"
                          placeholder="Dividing by zero shows “Error”, never Infinity." onChange={(e) => setDraft({ ...draft, statement: e.target.value })} />
                <div className="rounded-lg border bg-muted/30 p-3 text-sm">
                  <p className="font-medium">A written rule is kept and shown, and Smith follows it — but the app does not check it on a save.</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {model.hasModel && (
                      <Button size="sm" variant="outline" disabled={building}
                              onClick={() => setDraft({ id: draft.id, revision: draft.revision, kind: "condition_action",
                                                        ca: { ...emptyDraft(model.models[0] ?? null), id: draft.id, name: draft.name, statement: draft.statement },
                                                        on: ["create", "update"] })}>
                        <Wand2 className="mr-1.5 h-3.5 w-3.5" /> Make it a when → then rule
                      </Button>
                    )}
                    <Button size="sm" variant="outline" disabled={!draft.statement.trim()}
                            onClick={() => { askSmith(projectId, `Build this rule into the app so it really holds: “${draft.statement.trim()}”`); setDraft(null); }}>
                      <MessageSquare className="mr-1.5 h-3.5 w-3.5" /> Ask Smith to build it in
                    </Button>
                  </div>
                </div>
              </div>
            )}
            {draft.kind === "prerequisite" && (
              <div className="space-y-2 text-sm">
                <p>{draft.view.rule.statement}</p>
                <p className="text-muted-foreground">
                  Checked before {draft.view.gates.map((g) => g.name ?? g.id).join(", ") || "its workflows"} run. Smith sets prerequisites up;
                  here you can switch it on or off. To change it, ask Smith in the chat.
                </p>
              </div>
            )}
          </div>

          <aside className="space-y-4 overflow-y-auto border-l bg-muted/20 p-4">
            {(draft.kind === "condition_action" || draft.kind === "decision_table") && (
              <>
                <TestPanel projectId={projectId} payload={payload} ruleId={draft.id}
                           entityId={model.entityIdByName(entityName) ?? undefined} fields={fields} catalogue={catalogue}
                           onResult={setTest}
                           disabledReason={!entityName ? "Choose the record the rule is about." : undefined} />
                <div className="border-t pt-4">
                  <p className="mb-2 flex items-center gap-1.5 text-sm font-semibold"><GitBranch className="h-4 w-4 text-violet-600" /> Workflows</p>
                  <WorkflowsPanel projectId={projectId} view={saved} catalogue={catalogue} onChanged={onSaved} unsaved={!draft.id} />
                </div>
              </>
            )}
            {(draft.kind === "statement" || draft.kind === "prerequisite") && (
              <div className="space-y-2 text-xs text-muted-foreground">
                <p className="flex items-center gap-1.5 text-sm font-semibold text-foreground"><FileText className="h-4 w-4" /> About written rules</p>
                <p>When an app keeps records, a rule about them can be checked on every save — make it a when → then rule or a decision table.</p>
                <p>A rule about how the screens behave (colours, a calculator’s display) is built into the screens by Smith.</p>
              </div>
            )}
          </aside>
        </div>
      </SheetContent>
    </Sheet>
  );
}
