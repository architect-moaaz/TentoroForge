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
  List as ListIcon, Network, Plus, RefreshCw, Save, Scale, Search, ShieldCheck, Table2, Trash2, Wand2, Workflow, X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { askSmith, openWorkflow } from "@/lib/ask-smith";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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
import { RulesMap } from "./RulesMap";

type Draft = { id?: string; revision?: string } & (
  | { kind: "condition_action"; ca: ConditionActionDraft; on: FiresOn[] }
  | { kind: "decision_table"; name: string; statement: string; model: string | null; enabled: boolean;
      table: TableState; on: FiresOn[] }
  | { kind: "statement"; name: string; statement: string; enabled: boolean }
  | { kind: "prerequisite"; view: StudioView }
);

const BUSY_SAID: Record<string, string> = {
  building: "Forge is building this app. You can look at the rules, but not change them until the build is done. New rules appear here as they are made.",
  checking: "Forge is checking the app it just built. You can change rules again as soon as it is done.",
  smith: "Smith is working on this app. You can change rules again as soon as Smith is done. Any rule Smith changes appears here.",
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
  // List or Map, remembered per browser.
  const [layout, setLayoutState] = useState<"list" | "map">("list");
  useEffect(() => {
    try { if (localStorage.getItem("forge.rules.layout") === "map") setLayoutState("map"); } catch { /* storage off */ }
  }, []);
  const setLayout = (l: "list" | "map") => {
    setLayoutState(l);
    try { localStorage.setItem("forge.rules.layout", l); } catch { /* storage off */ }
  };
  const refresh = () => queryClient.invalidateQueries({ queryKey: key(projectId) });
  // Said once: workflow checks that repeated a rule were handed to the rule as the list was read.
  const [linkedNote, setLinkedNote] = useState<RulesResponse["linked"] | null>(null);
  useEffect(() => {
    if (data.linked?.length) {
      setLinkedNote(data.linked);
      queryClient.invalidateQueries({ queryKey: ["project", projectId, "workflows"] });
      queryClient.invalidateQueries({ queryKey: ["project", projectId, "business-rules-links"] });
    }
  }, [data.linked, projectId, queryClient]);

  const toggle = useMutation({
    mutationFn: (v: StudioView) =>
      api.patch(`/api/projects/${projectId}/business-rules/${v.rule.id}/enabled`, { enabled: !v.enabled, revision: v.revision }),
    onSuccess: (_r, v) => { toast.success(v.enabled ? "Turned off. Your app ignores this rule now." : "Turned on. Your app uses this rule now."); refresh(); },
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
              The rules your app follows. It checks them by itself every time something is saved — on every screen and in every workflow.
              Any change you make here works in your app as soon as you save it.
            </p>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button disabled={building} data-testid="new-rule"><Plus className="mr-1.5 h-4 w-4" /> New rule <ChevronDown className="ml-1 h-3.5 w-3.5" /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-80">
              <NewItem icon={Scale} title="If → then rule" disabled={!hasRecords}
                       says={hasRecords ? "If something is true, stop the save with a message, make a field required, or fill in a value." : "This app doesn’t save any data, so there is nothing to check."}
                       onSelect={() => create("condition_action")} />
              <NewItem icon={Table2} title="Table rule" disabled={!hasRecords}
                       says={hasRecords ? "Fill in a value based on other fields, with one row for each case." : "This app doesn’t save any data, so there is nothing to check."}
                       onSelect={() => create("decision_table")} />
              <NewItem icon={BookText} title="Note" says="A rule written in plain words. The app doesn’t check it, but Smith can build it in for you." onSelect={() => create("statement")} />
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="relative w-64">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a rule…" className="h-8 pl-8 text-sm" />
          </div>
          {hasRecords && (
            <div role="radiogroup" aria-label="Show the rules as" className="inline-flex rounded-lg border p-0.5 text-xs">
              {([["list", "List", ListIcon], ["map", "Map", Network]] as const).map(([id, label, Icon]) => (
                <button key={id} type="button" role="radio" aria-checked={layout === id} onClick={() => setLayout(id)}
                        className={cn("inline-flex items-center gap-1 rounded-md px-2.5 py-1 transition-colors",
                                      layout === id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}>
                  <Icon className="h-3.5 w-3.5" /> {label}
                </button>
              ))}
            </div>
          )}
          {model.models.length > 1 && (
            <select aria-label="Record" value={record} onChange={(e) => setRecord(e.target.value)} className="h-8 rounded-md border bg-background px-2 text-sm">
              {layout === "list" && <option value="all">Everything</option>}
              {model.models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          )}
          <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
            <span><b className="text-foreground">{views.filter((v) => v.enabled && v.enforced).length}</b> active</span>
            <span><b className="text-foreground">{views.filter((v) => v.enabled && !v.enforced).length}</b> notes</span>
            <span><b className="text-foreground">{views.filter((v) => !v.enabled).length}</b> turned off</span>
            <button type="button" onClick={refresh} aria-label="Reload" className="hover:text-foreground"><RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /></button>
          </div>
        </div>
      </div>

      {linkedNote && (
        <div className="flex items-start gap-2 border-b border-emerald-200 bg-emerald-50 px-6 py-2.5 text-xs text-emerald-900 dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-200" data-testid="rules-linked-note">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">
            <b>Your workflows now use these rules directly.</b> {linkedNote.length} check{linkedNote.length === 1 ? "" : "s"} in your workflows
            {" "}({Array.from(new Set(linkedNote.map((l) => l.name))).join(", ")}) repeated a rule word for word. {linkedNote.length === 1 ? "It now follows" : "They now follow"} the rule itself,
            so when you change a rule, your workflows change with it.
          </span>
          <button type="button" onClick={() => setLinkedNote(null)} aria-label="Close" className="hover:opacity-70"><X className="h-3.5 w-3.5" /></button>
        </div>
      )}

      {building && (
        <div className="flex items-center gap-2 border-b border-indigo-200 bg-indigo-50 px-6 py-2 text-xs text-indigo-900 dark:border-indigo-900/50 dark:bg-indigo-950/30 dark:text-indigo-200">
          <Hammer className="h-3.5 w-3.5" /> {BUSY_SAID[data.busy ?? "building"] ?? BUSY_SAID.building}
        </div>
      )}

      {layout === "map" && hasRecords ? (
        <div className="flex-1 p-4 motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300">
          <RulesMap projectId={projectId} views={views} catalogue={catalogue}
                    entityName={record !== "all" ? record : (views.find((v) => v.entityName && (v.kind === "condition_action" || v.kind === "decision_table"))?.entityName ?? model.models[0] ?? null)}
                    onOpen={open} />
        </div>
      ) : (
      <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
        {!hasRecords && (
          <div className="flex gap-3 rounded-xl border border-violet-200 bg-violet-50/60 p-4 text-sm dark:border-violet-900 dark:bg-violet-950/20" data-testid="no-records">
            <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-violet-600" />
            <div className="space-y-1">
              <p className="font-medium">This app doesn’t save any data, so there is nothing for a rule to check when saving.</p>
              <p className="text-muted-foreground">
                Its rules are about how its screens behave. They are kept here as notes so nothing you asked for is lost.
                Open one and choose <b>Ask Smith to build it in</b>, and Smith will build it into the screens.
              </p>
            </div>
          </div>
        )}

        {(data.planned ?? []).length > 0 && (
          <section className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 dark:border-amber-900 dark:bg-amber-950/20">
            <p className="text-sm font-medium">You asked for these, but there is no rule for them yet</p>
            <ul className="mt-2 space-y-1.5">
              {(data.planned ?? []).map((p) => (
                <li key={p.id} className="flex items-start gap-2 text-sm">
                  <span className="flex-1">{p.description}</span>
                  <Button size="sm" variant="outline" className="h-7 text-xs"
                          onClick={() => askSmith(projectId, `Make this a business rule that the app checks: “${p.description}”`)}>
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
              Rules are what your app checks and fills in by itself — for example “an expense above 5000 needs a manager’s note”.
              Make one with <b>New rule</b>, or just tell Smith in the chat.
            </p>
          </div>
        ) : shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">No rule matches your search.</p>
        ) : (
          <>
            <Group title="Active" hint="Your app checks these." views={enforced} catalogue={catalogue} onOpen={open} onToggle={(v) => toggle.mutate(v)} busy={building} />
            <Group title="Notes — the app doesn’t check these yet" hint={hasRecords ? "Open one to turn it into a real rule, or ask Smith." : "Ask Smith to build them into the app."} tone="amber"
                   views={written} catalogue={catalogue} onOpen={open} onToggle={(v) => toggle.mutate(v)} busy={building} />
            <Group title="Turned off" hint="Kept, but your app ignores them." tone="muted" views={off} catalogue={catalogue} onOpen={open} onToggle={(v) => toggle.mutate(v)} busy={building} />
          </>
        )}
      </div>
      )}

      <RuleSheet projectId={projectId} draft={draft} setDraft={setDraft} views={views} catalogue={catalogue}
                 model={model} building={building} onSaved={refresh} onCreated={open} />
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
  // Where the app checks it: the workflows that change what it looks at
  // first; if none do, every workflow that saves its record.
  const links = u?.links ?? [];
  const used = Array.from(new Set((links.some((l) => l.touches) ? links.filter((l) => l.touches) : links).map((l) => l.name)));
  return (
    <div className={cn("group flex items-start gap-3 rounded-xl border bg-card p-3.5 transition-shadow hover:shadow-sm", !view.enabled && "opacity-70")}
         data-rule={view.rule.id}>
      <button type="button" onClick={onOpen} aria-label={`Open ${view.rule.name}`} className="flex min-w-0 flex-1 items-start gap-3 text-left">
        <span className={cn("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                            view.kind === "decision_table" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                              : view.kind === "statement" ? "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                              : "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300")}>
          <Icon className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="font-medium group-hover:underline">{view.rule.name}</span>
            {view.entityName && <Badge variant="secondary" className="text-[10px]">{view.entityName}</Badge>}
            <Badge variant="outline" className="text-[10px]">{ORIGIN_LABEL[view.origin] ?? view.origin}</Badge>
          </span>
          <span className="mt-1 block text-sm text-muted-foreground">{ruleSentence(view, catalogue)}</span>
          <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
            <span className={view.enforced && view.enabled ? "text-emerald-700 dark:text-emerald-400" : "text-amber-700 dark:text-amber-400"}>
              {view.enabled ? RUNS_LABEL[view.runs] : "Turned off"}
            </span>
            {view.enabled && view.enforced && used.length > 0 && (
              <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400" data-testid="rule-used-in"
                    title={`Checked automatically when these workflows save: ${used.join(", ")}`}>
                <Workflow className="h-3 w-3" /> Used in {used.length <= 2 ? used.join(" and ") : `${used.length} workflows`}
              </span>
            )}
            {(u?.steps ?? []).map((s) => (
              <span key={s.workflow} className="inline-flex items-center gap-1 text-violet-700 dark:text-violet-300"><GitBranch className="h-3 w-3" /> extra check in {s.name}</span>
            ))}
            {view.enabled && (u?.copies?.length ?? 0) > 0 && (
              <span className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-400" data-testid="rule-has-copy">
                <AlertTriangle className="h-3 w-3" /> {u!.copies![0].name} has an older check that doesn’t match — open to fix
              </span>
            )}
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

function RuleSheet({ projectId, draft, setDraft, views, catalogue, model, building, onSaved, onCreated }: {
  projectId: string; draft: Draft | null; setDraft: (d: Draft | null) => void; views: StudioView[];
  catalogue: StudioCatalogue | null; model: ReturnType<typeof editorModel>; building: boolean; onSaved: () => void;
  onCreated: (v: StudioView) => void;
}) {
  const [check, setCheck] = useState<CheckAnswer | null>(null);
  const [saveProblems, setSaveProblems] = useState<string[]>([]);
  const [test, setTest] = useState<TestAnswer | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Just made: the list is refetching, so the rule is the save's answer until it arrives.
  const [made, setMade] = useState<StudioView | null>(null);
  const saved = draft?.id ? views.find((v) => v.rule.id === draft.id) ?? (made?.rule.id === draft.id ? made : null) : null;
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

  // A NEW RULE IS NOT SCOLDED BEFORE IT IS WRITTEN. What is missing is said
  // once the person has started (the draft differs from how it opened) or
  // tries to save; an existing rule is checked from the start.
  const opened = useRef<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  useEffect(() => { opened.current = null; setTouched(false); setConfirmClose(false); }, [draft?.id, draft?.kind]);
  useEffect(() => {
    const now = JSON.stringify(payload);
    if (opened.current === null) opened.current = now;
    else if (now !== opened.current) setTouched(true);
    setSaveProblems([]);   // what a save said is about the draft it was given, not this one
  }, [payload]);

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
      : api.post<{ rule: StudioView }>(`/api/projects/${projectId}/business-rules`, payload),
    // A new rule stays open, saved: what is next for it is often a workflow.
    onSuccess: (r) => {
      onSaved();
      const made = !draft?.id && (r as { rule?: StudioView } | undefined)?.rule;
      // Said as it is: a written rule is kept, not enforced; it runs in no workflow.
      const written = draft?.kind === "statement";
      const off = !!draft && (draft.kind === "condition_action" ? draft.ca.is_active === false
                              : draft.kind !== "prerequisite" && (draft as { enabled?: boolean }).enabled === false);
      if (made) {
        toast.success(written ? "Saved as a note. Smith follows it; the app checks it once you turn it into an if → then rule."
                      : off ? "Saved, but turned off. Your app ignores it until you turn it on."
                              : "Saved. Your app uses this rule now — on the right you can see the workflows that use it.");
        setMade(made); onCreated(made);
      } else {
        toast.success(written ? "Saved as a note." : off ? "Saved, but turned off." : "Saved. Your app uses the new version now.");
        setDraft(null);
      }
    },
    onError: (e) => {
      setSaveProblems(problemsOf(e));
      toast.error(problemsOf(e)[0] ?? "The rule could not be saved.");
      if ([409, 423].includes((e as ApiError).status)) onSaved();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/api/projects/${projectId}/business-rules/${draft!.id}${draft!.revision ? `?revision=${encodeURIComponent(draft!.revision)}` : ""}`),
    onSuccess: () => { toast.success("Rule deleted. Your app no longer uses it."); onSaved(); setDraft(null); },
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
  const showProblems = !!draft.id || touched || saveProblems.length > 0;
  const problems = saveProblems.length ? saveProblems : showProblems ? check?.problems ?? [] : [];
  const entityName = draft.kind === "condition_action" ? draft.ca.model_name : draft.kind === "decision_table" ? draft.model : null;
  const fields = (catalogue?.entities.find((e) => e.name === entityName)?.fields) ?? [];
  const asView = { ...(saved ?? {}), kind: draft.kind, entityName, rule: { ...(saved?.rule ?? {}), ...(payload ?? {}) } } as StudioView;
  const sentence = draft.kind === "condition_action" ? ruleSentence(asView, catalogue)
    : draft.kind === "decision_table" && draft.table.inputs.length + draft.table.outputs.length > 0 ? ruleSentence(asView, catalogue)
    : null;
  const canSave = !building && !stale && !gone && nameOf.trim().length > 0 && (check ? check.ok : true) && !save.isPending;
  // Save stays pressable on an untouched new rule: pressing it says what is missing.
  const saveDisabled = !canSave && (touched || !!draft.id || building || stale || gone);
  const Icon = KIND_ICON[draft.kind] ?? Scale;
  // Escape, a click outside or Close on unsaved work asks first: a table of
  // twenty rows was one keypress from gone.
  const requestClose = () => (touched && !save.isPending ? setConfirmClose(true) : setDraft(null));

  return (
    <>
    <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Delete “{nameOf || "this rule"}”?</DialogTitle>
          <DialogDescription>
            Your app stops using it right away{(saved?.usages?.links?.length ?? 0) > 0 ? `, including in ${Array.from(new Set(saved!.usages!.links!.map((l) => l.name))).join(", ")}` : ""}.
            You can still find it in the app’s history.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setConfirmDelete(false)}>Keep it</Button>
          <Button variant="destructive" onClick={() => remove.mutate()} disabled={remove.isPending || building}>
            {remove.isPending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}Delete it
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    <Dialog open={confirmClose} onOpenChange={setConfirmClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Leave without saving?</DialogTitle>
          <DialogDescription>
            {draft.id ? <>Your changes to “{nameOf || "this rule"}” are not saved. The app still uses the rule as it was.</>
                      : <>This new rule is not saved yet. If you leave, it will be lost.</>}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setConfirmClose(false)}>Keep editing</Button>
          <Button variant="destructive" onClick={() => { setConfirmClose(false); setDraft(null); }}>Discard changes</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    <Sheet open={!!draft} onOpenChange={(o) => !o && requestClose()}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-[1180px]" data-testid="rule-sheet">
        <div className="flex items-center gap-3 border-b px-5 py-3">
          <Icon className="h-5 w-5 text-violet-600" />
          <div className="min-w-0 flex-1">
            <SheetTitle className="sr-only">{nameOf || "New rule"}</SheetTitle>
            <SheetDescription className="sr-only">Edit a business rule</SheetDescription>
            <input value={nameOf} onChange={(e) => setName(e.target.value)} disabled={draft.kind === "prerequisite"}
                   placeholder={draft.kind === "decision_table" ? "Give it a name — e.g. Category by amount" : "Give it a name — e.g. Big expenses need a note"}
                   aria-label="Rule name" className="w-full bg-transparent text-lg font-semibold outline-none placeholder:text-muted-foreground/60" />
            <p className="text-xs text-muted-foreground">
              {{ condition_action: "If → then rule", decision_table: "Table rule", statement: "Note — the app doesn’t check it", prerequisite: "Set up by Smith" }[draft.kind]}
            </p>
          </div>
          <label className="flex items-center gap-2 text-xs">
            <Switch checked={enabled} onCheckedChange={setEnabled} disabled={building} aria-label="On or off" /> {enabled ? "On" : "Off"}
          </label>
          {draft.id && draft.kind !== "prerequisite" && (
            // Asked in a dialog, not by turning this button into "Remove it" in
            // place — a double-click removed a live rule.
            <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)} disabled={building} aria-label="Delete rule" title="Delete this rule"><Trash2 className="h-4 w-4" /></Button>
          )}
          <Button variant="ghost" size="sm" onClick={requestClose}><X className="mr-1 h-4 w-4" /> Close</Button>
          <Button size="sm" onClick={() => (canSave ? save.mutate() : (setTouched(true), setSaveProblems(check?.problems?.length ? check.problems : ["Give the rule a name."])))}
                  disabled={saveDisabled} data-testid="save-rule">
            {save.isPending ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />} Save
          </Button>
        </div>

        {(stale || gone) && (
          <div className="flex items-center gap-2 border-b bg-amber-50 px-5 py-2 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
            <AlertTriangle className="h-3.5 w-3.5" />
            {gone ? "This rule was deleted while you had it open." : "Someone (or Smith) changed this rule while you had it open."}
            {saved && <Button size="sm" variant="outline" className="ml-auto h-7 text-xs" onClick={() => setDraft(null)}>Close and reopen it</Button>}
          </div>
        )}

        {/* Wide: editor and side panel scroll on their own. Narrow: one column, one scroll. */}
        <div className="grid h-[calc(100%-57px)] grid-cols-1 overflow-y-auto lg:grid-cols-[1fr_380px] lg:overflow-hidden">
          <div className="space-y-4 p-5 lg:overflow-y-auto">
            {sentence && (
              <p className="rounded-lg bg-muted/50 px-3 py-2 text-sm" data-testid="reads-as">
                <span className="mr-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">In plain words</span>{sentence}
              </p>
            )}
            {problems.length > 0 && (
              <ul className="space-y-1 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200" data-testid="problems">
                {problems.map((p, i) => <li key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{p}</li>)}
              </ul>
            )}
            {(check?.advice ?? []).length > 0 && (
              <ul className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                {check!.advice!.map((a, i) => <li key={i} className="flex gap-1.5"><Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0" />{a}</li>)}
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
                  <span>When</span>
                  <select aria-label="Record" value={draft.model ?? ""} disabled={building || draft.table.inputs.length + draft.table.outputs.length > 0}
                          title={draft.table.inputs.length ? "Remove the columns first to choose something else" : undefined}
                          onChange={(e) => setDraft({ ...draft, model: e.target.value })}
                          className="h-8 rounded-md border bg-background px-2 font-medium">
                    {model.models.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                  <span>is</span>
                  {(["create", "update"] as FiresOn[]).map((e) => (
                    <button key={e} type="button" aria-pressed={draft.on.includes(e)} disabled={building}
                            onClick={() => { const n = draft.on.includes(e) ? draft.on.filter((x) => x !== e) : [...draft.on, e]; if (n.length) setDraft({ ...draft, on: n }); }}
                            className={cn("rounded-full border px-3 py-1 text-xs font-medium", draft.on.includes(e) ? "border-sky-600 bg-sky-600 text-white" : "hover:bg-muted")}>
                      {e === "create" ? "added" : "changed"}
                    </button>
                  ))}
                  <span>— the table fills in the columns on the right.</span>
                </div>
                <TableEditor value={draft.table} onChange={(table) => setDraft({ ...draft, table })} fields={fields}
                             findings={check?.findings ?? []} matched={test?.focus?.matched} used={test?.focus?.used} disabled={building} />
                <label className="block space-y-1">
                  <span className="text-xs font-medium">Describe it in one sentence <span className="font-normal text-muted-foreground">(optional — Forge writes it if you leave it empty)</span></span>
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
                  <p className="font-medium">A note is kept and Smith follows it, but the app doesn’t check it when something is saved.</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {model.hasModel && (
                      <Button size="sm" variant="outline" disabled={building}
                              onClick={() => setDraft({ id: draft.id, revision: draft.revision, kind: "condition_action",
                                                        ca: { ...emptyDraft(model.models[0] ?? null), id: draft.id, name: draft.name, statement: draft.statement },
                                                        on: ["create", "update"] })}>
                        <Wand2 className="mr-1.5 h-3.5 w-3.5" /> Turn it into an if → then rule
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
                  Checked before {draft.view.gates.map((g) => g.name ?? g.id).join(", ") || "its workflows"} start. Smith set this up;
                  here you can turn it on or off. To change it, ask Smith in the chat.
                </p>
              </div>
            )}
          </div>

          <aside className="space-y-4 border-t bg-muted/20 p-4 lg:overflow-y-auto lg:border-l lg:border-t-0">
            {(draft.kind === "condition_action" || draft.kind === "decision_table") && (
              <>
                <TestPanel projectId={projectId} payload={payload} ruleId={draft.id}
                           entityId={model.entityIdByName(entityName) ?? undefined} fields={fields} catalogue={catalogue}
                           onResult={setTest}
                           disabledReason={!entityName ? "Choose the record the rule is about." : undefined} />
                <div className="border-t pt-4">
                  <p className="mb-2 flex items-center gap-1.5 text-sm font-semibold"><Workflow className="h-4 w-4 text-emerald-600" /> Where this rule is used</p>
                  <WorkflowsPanel projectId={projectId} view={saved} catalogue={catalogue} onChanged={onSaved} unsaved={!draft.id || (!!saved && saved.kind !== draft.kind)}
                                  onOpenWorkflow={(w) => { setDraft(null); openWorkflow(projectId, w); }} />
                </div>
              </>
            )}
            {(draft.kind === "statement" || draft.kind === "prerequisite") && (
              <div className="space-y-2 text-xs text-muted-foreground">
                <p className="flex items-center gap-1.5 text-sm font-semibold text-foreground"><FileText className="h-4 w-4" /> About notes</p>
                <p>If the rule is about data your app saves, turn it into an if → then rule or a table rule, and the app will check it every time.</p>
                <p>If it is about how the screens behave (colours, what a display shows), ask Smith to build it into the screens.</p>
              </div>
            )}
          </aside>
        </div>
      </SheetContent>
    </Sheet>
    </>
  );
}
