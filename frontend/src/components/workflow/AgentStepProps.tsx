"use client";

/**
 * The properties of an agent step: which assistant does it, what it is asked, what it hands back, how much it may do
 * by itself, and what happens when it cannot finish.
 *
 * Everything the person types is saved straight into the step's config (the field names are the contract's, so the
 * build gate and the app runtime read exactly what is written here). Sentences in the red and amber boxes are what the
 * build would say, said now.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, Loader2, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import {
  AUTONOMY_CHOICES,
  AUTONOMY_WARNING,
  BRIEF_PURPOSE_MAX,
  FAILURE_CHOICES,
  OUTPUT_TYPE_CHOICES,
  STANDARD_ENVELOPE,
  STEP_LIMITS,
  agentStepIssues,
  asFields,
  autonomyOf,
  briefProblem,
  clampLimit,
  draftFromBrief,
  enumProblem,
  isWorkflowOnly,
  newOutputField,
  outputNameProblem,
  parseNameList,
  readFromBrief,
  toBrief,
  type BriefDraft,
  type LimitKey,
  type StepIssue,
} from "@/lib/agent-step";
import type { AgentAutonomy, AgentOnFailure, AgentOutputField, AgentOutputType } from "@/types/ai-features";
import type { AppModel } from "@/types/app-model";
import type { ProcessVariable, WorkflowNodeConfig, WorkflowNodeSerialized } from "@/types/workflow";
import { VariablePicker } from "./VariablePicker";
import type { WorkflowVariable } from "./workflowVariables";
import { assistantsKey, useAssistantTools, useAssistants } from "./agentStepData";

interface AgentStepPropsProps {
  nodeId: string;
  config: WorkflowNodeConfig;
  allNodes: WorkflowNodeSerialized[];
  allEdges?: Array<{ source: string; target: string }>;
  appModel: AppModel | null;
  projectId?: string;
  workflowId?: string;
  processVariables?: ProcessVariable[];
  variables: WorkflowVariable[];
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
}

const sectionTitle = "text-[10px] font-semibold uppercase text-muted-foreground";

export function AgentStepProps({
  nodeId,
  config,
  allNodes,
  allEdges,
  appModel,
  projectId,
  workflowId,
  processVariables,
  variables,
  onUpdate,
}: AgentStepPropsProps) {
  const { assistants, loading: assistantsLoading, failed: assistantsFailed } = useAssistants(projectId);
  const { tools, loading: toolsLoading } = useAssistantTools(projectId, config.agentId);

  const autonomy = autonomyOf(config);
  const fields = asFields(config.outputFields);
  const allowed = Array.isArray(config.allowedWriteTools) ? config.allowedWriteTools : [];

  // When the person flips to Suggest and back, the changes they had listed come back with them.
  const rememberedTools = useRef<string[]>(allowed);
  useEffect(() => {
    if (allowed.length) rememberedTools.current = allowed;
  }, [allowed]);

  const issues = useMemo(
    () =>
      agentStepIssues({
        config,
        stepId: nodeId,
        nodes: allNodes,
        edges: allEdges,
        tools,
        workflowId,
        // Only say "cannot be found" once the list has really loaded.
        assistantIds: projectId && !assistantsLoading && !assistantsFailed ? assistants.map((a) => a.id) : undefined,
      }),
    [config, nodeId, allNodes, allEdges, tools, workflowId, projectId, assistants, assistantsLoading, assistantsFailed],
  );
  const errors = issues.filter((i) => i.level === "error");

  const chooseAutonomy = (next: AgentAutonomy) => {
    if (next === autonomy) return;
    const patch: Partial<WorkflowNodeConfig> = { autonomy: next };
    if (next === "suggest") {
      // Suggest never changes anything, so no list of allowed changes is left lying in the saved step.
      patch.allowedWriteTools = undefined;
      patch.minConfidence = undefined;
    } else {
      if (allowed.length === 0 && rememberedTools.current.length) patch.allowedWriteTools = rememberedTools.current;
      patch.minConfidence = next === "limited" ? (config.minConfidence ?? STEP_LIMITS.minConfidence.default) : undefined;
      patch.maxActions = config.maxActions ?? STEP_LIMITS.maxActions.default;
    }
    onUpdate(patch);
  };

  return (
    <div className="space-y-4" data-testid="agent-step-props">
      {errors.length > 0 && (
        <p className="rounded border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-800" role="status">
          {errors.length === 1 ? "1 thing to fix before this step will build." : `${errors.length} things to fix before this step will build.`}
        </p>
      )}

      {/* --- The assistant --- */}
      <section className="space-y-2" aria-label="Assistant">
        <Label className={sectionTitle}>Assistant</Label>
        <AssistantPicker
          projectId={projectId}
          config={config}
          assistants={assistants}
          loading={assistantsLoading}
          failed={assistantsFailed}
          nodeId={nodeId}
          workflowId={workflowId}
          onPick={(agentId) => onUpdate({ agentId, agentBrief: undefined })}
        />
        <IssueList issues={issues} area="assistant" />
      </section>

      {/* --- The task --- */}
      <section className="space-y-2" aria-label="Task">
        <TaskBox
          value={config.task ?? ""}
          onChange={(task) => onUpdate({ task })}
          nodeId={nodeId}
          appModel={appModel}
          allNodes={allNodes}
          allEdges={allEdges}
          processVariables={processVariables}
        />
        <div>
          <Label className={sectionTitle}>Facts to hand over</Label>
          <p className="mb-1 text-[10px] leading-snug text-muted-foreground">
            Named values the assistant sees as labelled facts, for example ownerName from a variable.
          </p>
          <FactsEditor
            value={config.input}
            variables={variables}
            onChange={(input) => onUpdate({ input })}
          />
        </div>
        <IssueList issues={issues} area="task" />
      </section>

      {/* --- What it hands back --- */}
      <section className="space-y-2" aria-label="Answers">
        <Label className={sectionTitle}>What it hands back</Label>
        <p className="text-[10px] leading-snug text-muted-foreground">
          Each answer can be read by later steps as {"{{" + nodeId + ".result.name}}"}.
        </p>
        <AnswersEditor
          fields={fields}
          onChange={(outputFields) => onUpdate({ outputFields })}
        />
        <IssueList issues={issues} area="answers" />
        <div className="rounded bg-muted/40 px-2 py-1.5">
          <p className="text-[10px] font-medium text-muted-foreground">Always handed back as well</p>
          <ul className="mt-0.5 space-y-0.5">
            {STANDARD_ENVELOPE.map((s) => (
              <li key={s.name} className="text-[10px] text-muted-foreground">
                <code className="font-mono text-slate-600">{s.name}</code> {s.meaning}
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* --- Autonomy --- */}
      <section className="space-y-2" aria-label="How much it may do by itself">
        <Label className={sectionTitle}>How much it may do by itself</Label>
        <div role="radiogroup" aria-label="How much it may do by itself" className="space-y-1">
          {AUTONOMY_CHOICES.map((c) => (
            <button
              key={c.value}
              type="button"
              role="radio"
              aria-checked={autonomy === c.value}
              onClick={() => chooseAutonomy(c.value)}
              className={`w-full rounded-md border px-2 py-1.5 text-left transition-colors ${
                autonomy === c.value ? "border-indigo-500 bg-indigo-50" : "border-gray-200 hover:bg-muted/40"
              }`}
            >
              <span className="block text-xs font-semibold text-slate-800">{c.label}</span>
              <span className="block text-[11px] leading-snug text-muted-foreground">{c.explain}</span>
            </button>
          ))}
        </div>

        {autonomy !== "suggest" && (
          <div className="space-y-2 rounded-md border border-amber-200 bg-amber-50/60 p-2">
            <p className="text-[11px] font-medium text-amber-900" data-testid="autonomy-warning">{AUTONOMY_WARNING}</p>
            <WriteToolsPicker
              tools={tools}
              toolsLoading={toolsLoading}
              hasAssistant={!!config.agentId}
              allowed={allowed}
              onChange={(allowedWriteTools) => onUpdate({ allowedWriteTools })}
            />
            {autonomy === "limited" && (
              <ConfidenceSlider
                value={config.minConfidence ?? STEP_LIMITS.minConfidence.default}
                onChange={(minConfidence) => onUpdate({ minConfidence })}
              />
            )}
            <LimitInput
              id="agent-max-actions"
              label="Most changes at once"
              limit="maxActions"
              value={config.maxActions}
              onCommit={(maxActions) => onUpdate({ maxActions })}
            />
          </div>
        )}
        <IssueList issues={issues} area="autonomy" />
      </section>

      {/* --- Limits --- */}
      <section className="space-y-2" aria-label="Limits">
        <Label className={sectionTitle}>Limits</Label>
        <LimitInput id="agent-max-turns" label="Most turns" limit="maxTurns" value={config.maxTurns} onCommit={(maxTurns) => onUpdate({ maxTurns })} />
        <LimitInput id="agent-timeout" label="Time limit (seconds)" limit="timeoutSec" value={config.timeoutSec} onCommit={(timeoutSec) => onUpdate({ timeoutSec })} />
        <LimitInput id="agent-max-tokens" label="Size limit (tokens)" limit="maxTokens" value={config.maxTokens} onCommit={(maxTokens) => onUpdate({ maxTokens })} />
        <IssueList issues={issues} area="limits" />
      </section>

      {/* --- If it cannot finish --- */}
      <section className="space-y-2" aria-label="If it cannot finish">
        <Label className={sectionTitle}>If it cannot finish</Label>
        <div role="radiogroup" aria-label="If it cannot finish" className="space-y-1">
          {FAILURE_CHOICES.map((c) => {
            const chosen = (config.onFailure ?? "human") === c.value;
            return (
              <button
                key={c.value}
                type="button"
                role="radio"
                aria-checked={chosen}
                onClick={() => onUpdate({ onFailure: c.value as AgentOnFailure })}
                className={`w-full rounded-md border px-2 py-1.5 text-left transition-colors ${
                  chosen ? "border-indigo-500 bg-indigo-50" : "border-gray-200 hover:bg-muted/40"
                }`}
              >
                <span className="block text-xs font-semibold text-slate-800">{c.label}</span>
                <span className="block text-[11px] leading-snug text-muted-foreground">{c.explain}</span>
              </button>
            );
          })}
        </div>
        <IssueList issues={issues} area="failure" />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Problems, in plain words
// ---------------------------------------------------------------------------

function IssueList({ issues, area }: { issues: StepIssue[]; area: StepIssue["area"] }) {
  // A problem with one answer is written under that answer instead.
  const mine = issues.filter((i) => i.area === area && i.row === undefined);
  if (mine.length === 0) return null;
  return (
    <ul className="space-y-1" data-testid={`issues-${area}`}>
      {mine.map((i, n) => (
        <li
          key={`${n}-${i.text}`}
          role={i.level === "error" ? "alert" : undefined}
          className={
            i.level === "error"
              ? "rounded border border-red-200 bg-red-50 px-2 py-1 text-[11px] leading-snug text-red-800"
              : "rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] leading-snug text-amber-900"
          }
        >
          {i.text}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// The assistant picker, and "create one for this step"
// ---------------------------------------------------------------------------

function AssistantPicker({
  projectId,
  config,
  assistants,
  loading,
  failed,
  nodeId,
  workflowId,
  onPick,
}: {
  projectId?: string;
  config: WorkflowNodeConfig;
  assistants: { id: string; name: string; description: string | null; node_count: number }[];
  loading: boolean;
  failed: boolean;
  nodeId: string;
  workflowId?: string;
  onPick: (agentId: string) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [justMade, setJustMade] = useState<{ name?: string; warnings: string[] } | null>(null);

  if (!projectId) {
    return <p className="text-[11px] text-muted-foreground">Open this workflow from a project to pick an assistant.</p>;
  }

  return (
    <div className="space-y-2">
      {loading ? (
        <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Looking for assistants
        </p>
      ) : failed ? (
        <p className="text-[11px] text-red-700">Could not load the assistants. Try again in a moment.</p>
      ) : assistants.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">This project has no assistants yet. Create one for this step below.</p>
      ) : (
        <div role="radiogroup" aria-label="Assistant" className="max-h-48 space-y-1 overflow-y-auto pr-0.5">
          {assistants.map((a) => {
            const chosen = config.agentId === a.id;
            return (
              <button
                key={a.id}
                type="button"
                role="radio"
                aria-checked={chosen}
                onClick={() => onPick(a.id)}
                className={`flex w-full items-start gap-2 rounded-md border px-2 py-1.5 text-left transition-colors ${
                  chosen ? "border-indigo-500 bg-indigo-50" : "border-gray-200 hover:bg-muted/40"
                }`}
              >
                <Bot className="mt-0.5 h-3.5 w-3.5 shrink-0 text-purple-600" />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className="truncate text-xs font-semibold text-slate-800">{a.name}</span>
                    {isWorkflowOnly(a.id) && (
                      <span className="rounded border border-gray-200 px-1 text-[9px] text-muted-foreground">Made for a workflow</span>
                    )}
                  </span>
                  {a.description && (
                    <span className="line-clamp-2 block text-[11px] leading-snug text-muted-foreground">{a.description}</span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {config.agentId && !assistants.some((a) => a.id === config.agentId) && !loading && !failed && (
        <p className="text-[11px] text-muted-foreground">
          Chosen: <code className="font-mono">{config.agentId}</code>
        </p>
      )}

      {!config.agentId && config.agentBrief && (
        <div className="rounded border border-dashed border-purple-300 bg-purple-50/50 px-2 py-1.5">
          <p className="text-[10px] font-medium text-purple-800">Planned assistant</p>
          <p className="text-[11px] leading-snug text-slate-700">{config.agentBrief.purpose}</p>
        </div>
      )}

      {justMade && (
        <div className="space-y-1" data-testid="assistant-made">
          <p className="text-[11px] text-green-800">
            {justMade.name ? `Made "${justMade.name}" and chose it for this step.` : "Made the assistant and chose it for this step."}
          </p>
          {justMade.warnings.map((w, i) => (
            <p key={i} className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] leading-snug text-amber-900">{w}</p>
          ))}
        </div>
      )}

      {creating ? (
        <BriefForm
          projectId={projectId}
          nodeId={nodeId}
          workflowId={workflowId}
          initial={draftFromBrief(config.agentBrief)}
          onCancel={() => setCreating(false)}
          onMade={(made) => {
            onPick(made.agentId);
            setJustMade({ name: made.name, warnings: made.warnings });
            setCreating(false);
          }}
        />
      ) : (
        <Button variant="outline" size="sm" className="h-7 w-full text-xs" onClick={() => { setJustMade(null); setCreating(true); }}>
          <Plus className="mr-1 h-3 w-3" />
          Create an assistant for this step
        </Button>
      )}
    </div>
  );
}

function BriefForm({
  projectId,
  nodeId,
  workflowId,
  initial,
  onCancel,
  onMade,
}: {
  projectId: string;
  nodeId: string;
  workflowId?: string;
  initial: BriefDraft;
  onCancel: () => void;
  onMade: (made: { agentId: string; name?: string; warnings: string[] }) => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<BriefDraft>(initial);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const problem = briefProblem(draft);

  const submit = async () => {
    if (problem || busy) return;
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { brief: toBrief(draft), workflowId, stepId: nodeId };
      if (name.trim()) body.name = name.trim();
      const raw = await api.post<unknown>(`/api/projects/${projectId}/agent-definitions/from-brief`, body);
      const made = readFromBrief(raw);
      if (!made) {
        setError("The platform did not say which assistant it made. Try again.");
        return;
      }
      // The Agents tab and this picker read the same list: tell it there is a new assistant, and wait for the list to
      // say so before choosing it (choosing first would flash "cannot be found" for the moment the list is old).
      try {
        await queryClient.invalidateQueries({ queryKey: assistantsKey(projectId) });
      } catch {
        /* the list comes back on its own next time; the assistant is made either way */
      }
      onMade(made);
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : "Could not create the assistant. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2 rounded-md border border-purple-200 bg-purple-50/40 p-2" data-testid="brief-form">
      <div>
        <Label className="text-xs" htmlFor="brief-purpose">What should it do?</Label>
        <Textarea
          id="brief-purpose"
          className="mt-1 min-h-[56px] text-xs"
          maxLength={BRIEF_PURPOSE_MAX + 200}
          placeholder="Work out how urgent a visit request is, using the pet's history"
          value={draft.purpose}
          onChange={(e) => setDraft({ ...draft, purpose: e.target.value })}
        />
      </div>
      <div>
        <Label className="text-xs" htmlFor="brief-reads">What may it read?</Label>
        <Textarea
          id="brief-reads"
          className="mt-1 min-h-[56px] font-mono text-xs"
          placeholder={"pets\nvaccinations\nvet_schedules"}
          value={draft.reads}
          onChange={(e) => setDraft({ ...draft, reads: e.target.value })}
        />
        <p className="mt-0.5 text-[10px] text-muted-foreground">One table or tool name per line.</p>
      </div>
      <div className="space-y-1">
        <Label className="text-xs">What may it change? (optional)</Label>
        {draft.mayChange.map((m, i) => (
          <div key={i} className="flex gap-1">
            <Input
              aria-label={`Change ${i + 1} tool`}
              className="h-7 w-[40%] font-mono text-xs"
              placeholder="tool name"
              value={m.tool}
              onChange={(e) => setDraft({ ...draft, mayChange: draft.mayChange.map((x, j) => (j === i ? { ...x, tool: e.target.value } : x)) })}
            />
            <Input
              aria-label={`Change ${i + 1} reason`}
              className="h-7 flex-1 text-xs"
              placeholder="why it may"
              value={m.why}
              onChange={(e) => setDraft({ ...draft, mayChange: draft.mayChange.map((x, j) => (j === i ? { ...x, why: e.target.value } : x)) })}
            />
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0"
              aria-label={`Remove change ${i + 1}`}
              onClick={() => setDraft({ ...draft, mayChange: draft.mayChange.filter((_, j) => j !== i) })}
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        ))}
        <Button variant="ghost" size="sm" className="h-6 px-1 text-[11px]" onClick={() => setDraft({ ...draft, mayChange: [...draft.mayChange, { tool: "", why: "" }] })}>
          <Plus className="mr-1 h-3 w-3" />
          Add a change
        </Button>
      </div>
      <div>
        <Label className="text-xs" htmlFor="brief-name">Name (optional)</Label>
        <Input id="brief-name" className="mt-1 h-7 text-xs" placeholder="Triage" value={name} onChange={(e) => setName(e.target.value)} />
      </div>

      {error && <p role="alert" className="rounded border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-800">{error}</p>}
      {problem && (draft.purpose || draft.reads) && <p className="text-[11px] text-muted-foreground">{problem}</p>}

      <div className="flex gap-1.5">
        <Button size="sm" className="h-7 text-xs" disabled={!!problem || busy} onClick={submit}>
          {busy && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
          {busy ? "Creating" : "Create assistant"}
        </Button>
        <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={onCancel} disabled={busy}>Cancel</Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The task text, with the variable picker
// ---------------------------------------------------------------------------

function TaskBox({
  value,
  onChange,
  nodeId,
  appModel,
  allNodes,
  allEdges,
  processVariables,
}: {
  value: string;
  onChange: (v: string) => void;
  nodeId: string;
  appModel: AppModel | null;
  allNodes: WorkflowNodeSerialized[];
  allEdges?: Array<{ source: string; target: string }>;
  processVariables?: ProcessVariable[];
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  // A picked variable goes where the cursor is (or the end), not onto the description like the other steps.
  const insert = (variable: string) => {
    const el = ref.current;
    const at = el && typeof el.selectionStart === "number" ? el.selectionStart : value.length;
    const end = el && typeof el.selectionEnd === "number" ? el.selectionEnd : at;
    onChange(value.slice(0, at) + variable + value.slice(end));
  };
  return (
    <div>
      <Label className={sectionTitle} htmlFor="agent-task">What to do this time</Label>
      <Textarea
        id="agent-task"
        ref={ref}
        className="mt-1 min-h-[80px] text-xs"
        placeholder="Work out how urgent {{trigger.reason}} is for this pet and suggest a visit"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <details className="mt-1">
        <summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground">Insert a variable</summary>
        <div className="mt-1 rounded border p-2">
          <VariablePicker
            appModel={appModel}
            nodes={allNodes}
            edges={allEdges}
            currentNodeId={nodeId}
            processVariables={processVariables}
            onInsert={insert}
          />
        </div>
      </details>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Facts handed over (name and a variable)
// ---------------------------------------------------------------------------

/**
 * Name and value on two lines, so both stay readable in a narrow panel. The value is the {{variable}} text itself, and
 * the small menu beside it writes one in. Rows are kept here while being edited (a blank row has no name yet and is not
 * saved); a change made from outside, like undo, replaces them.
 */
function FactsEditor({
  value,
  variables,
  onChange,
}: {
  value: Record<string, string> | undefined;
  variables: WorkflowVariable[];
  onChange: (next: Record<string, string>) => void;
}) {
  type Row = { name: string; value: string };
  const toRows = (v: Record<string, unknown> | undefined): Row[] =>
    Object.entries(v && typeof v === "object" ? v : {}).map(([name, val]) => ({ name, value: String(val ?? "") }));
  const [rows, setRows] = useState<Row[]>(() => toRows(value));
  const saved = useRef(JSON.stringify(value ?? {}));
  useEffect(() => {
    const now = JSON.stringify(value ?? {});
    if (now !== saved.current) {
      saved.current = now;
      setRows(toRows(value));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const commit = (next: Row[]) => {
    setRows(next);
    const obj: Record<string, string> = {};
    for (const r of next) if (r.name.trim()) obj[r.name.trim()] = r.value;
    saved.current = JSON.stringify(obj);
    onChange(obj);
  };
  const set = (i: number, patch: Partial<Row>) => commit(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const names = rows.map((r) => r.name.trim()).filter(Boolean);
  const repeated = names.find((n, i) => names.indexOf(n) !== i);

  return (
    <div className="space-y-1.5">
      {rows.map((r, i) => (
        <div key={i} className="space-y-1 rounded-md border border-gray-200 p-1.5" data-testid="fact-row">
          <div className="flex gap-1">
            <Input
              aria-label={`Fact ${i + 1} name`}
              className="h-7 flex-1 font-mono text-xs"
              placeholder="ownerName"
              value={r.name}
              onChange={(e) => set(i, { name: e.target.value })}
            />
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0"
              aria-label={`Remove fact ${i + 1}`}
              onClick={() => commit(rows.filter((_, j) => j !== i))}
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
          <div className="flex gap-1">
            <Input
              aria-label={`Fact ${i + 1} value`}
              className="h-7 min-w-0 flex-1 font-mono text-xs"
              placeholder="{{trigger.ownerName}}"
              value={r.value}
              onChange={(e) => set(i, { value: e.target.value })}
            />
            <select
              aria-label={`Fact ${i + 1} pick a variable`}
              className="h-7 w-[84px] shrink-0 rounded-md border border-input bg-transparent px-1 text-xs"
              value=""
              onChange={(e) => e.target.value && set(i, { value: `{{${e.target.value}}}` })}
            >
              <option value="">Variable</option>
              {variables.map((v) => (
                <option key={v.path} value={v.path}>{v.path}</option>
              ))}
            </select>
          </div>
        </div>
      ))}
      <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => commit([...rows, { name: "", value: "" }])}>
        <Plus className="mr-1 h-3 w-3" />
        Add a fact
      </Button>
      {rows.some((r) => !r.name.trim()) && <p className="text-[11px] text-red-700">One of the facts has no name yet, so it is not saved.</p>}
      {repeated && <p className="text-[11px] text-red-700">Two facts are both called "{repeated}". Only the last one is kept.</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The answers editor
// ---------------------------------------------------------------------------

function AnswersEditor({ fields, onChange }: { fields: AgentOutputField[]; onChange: (f: AgentOutputField[]) => void }) {
  const set = (i: number, patch: Partial<AgentOutputField>) =>
    onChange(fields.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  return (
    <div className="space-y-2">
      {fields.map((f, i) => {
        const nameProblem = outputNameProblem(f.name, fields.filter((_, j) => j !== i).map((o) => o.name));
        const valuesProblem = enumProblem(f);
        return (
          <div key={i} className="space-y-1 rounded-md border border-gray-200 p-2" data-testid="answer-row">
            <div className="flex gap-1">
              <Input
                aria-label={`Answer ${i + 1} name`}
                aria-invalid={!!nameProblem}
                className={`h-7 flex-1 font-mono text-xs ${nameProblem ? "border-red-400" : ""}`}
                placeholder="urgency"
                value={f.name}
                onChange={(e) => set(i, { name: e.target.value })}
              />
              <select
                aria-label={`Answer ${i + 1} type`}
                className="h-7 rounded-md border border-input bg-transparent px-1 text-xs"
                value={f.type}
                onChange={(e) => {
                  const type = e.target.value as AgentOutputType;
                  set(i, { type, values: type === "enum" ? f.values ?? [] : undefined });
                }}
              >
                {OUTPUT_TYPE_CHOICES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                aria-label={`Remove answer ${i + 1}`}
                onClick={() => onChange(fields.filter((_, j) => j !== i))}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
            {f.type === "enum" && (
              <EnumValues
                label={`Answer ${i + 1} allowed values`}
                values={f.values ?? []}
                onChange={(values) => set(i, { values })}
              />
            )}
            <Input
              aria-label={`Answer ${i + 1} description`}
              className="h-7 text-xs"
              placeholder="What this answer means"
              value={f.description}
              onChange={(e) => set(i, { description: e.target.value })}
            />
            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <input
                type="checkbox"
                checked={f.required !== false}
                onChange={(e) => set(i, { required: e.target.checked })}
              />
              It must always give this answer
            </label>
            {nameProblem && <p className="text-[11px] leading-snug text-red-700">{nameProblem}</p>}
            {valuesProblem && <p className="text-[11px] leading-snug text-red-700">{valuesProblem}</p>}
          </div>
        );
      })}
      <Button
        variant="outline"
        size="sm"
        className="h-7 text-xs"
        onClick={() => onChange([...fields, newOutputField(fields)])}
      >
        <Plus className="mr-1 h-3 w-3" />
        Add an answer
      </Button>
    </div>
  );
}

/** Allowed values as a comma separated box. The text is kept as typed, so a trailing comma is not eaten. */
function EnumValues({ label, values, onChange }: { label: string; values: string[]; onChange: (v: string[]) => void }) {
  const parse = (t: string) => t.split(",").map((s) => s.trim()).filter(Boolean);
  const [text, setText] = useState(values.join(", "));
  // A row removed above this one shifts the values in: follow them.
  useEffect(() => {
    const now = parse(text);
    if (now.length !== values.length || now.some((v, i) => v !== values[i])) setText(values.join(", "));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values]);
  return (
    <Input
      aria-label={label}
      title="Allowed values, separated by commas"
      className="h-7 text-xs"
      placeholder="Allowed values, separated by commas"
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        onChange(parse(e.target.value));
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Which changes it may make
// ---------------------------------------------------------------------------

function WriteToolsPicker({
  tools,
  toolsLoading,
  hasAssistant,
  allowed,
  onChange,
}: {
  tools: ReturnType<typeof useAssistantTools>["tools"];
  toolsLoading: boolean;
  hasAssistant: boolean;
  allowed: string[];
  onChange: (names: string[]) => void;
}) {
  const [text, setText] = useState(allowed.join("\n"));
  if (toolsLoading) {
    return <p className="text-[11px] text-muted-foreground">Reading this assistant's tools</p>;
  }
  if (!tools) {
    // The tools could not be read (no assistant yet, or an older platform): ask for the names in words.
    return (
      <div>
        <Label className="text-xs" htmlFor="agent-write-tools">Changes it may make</Label>
        <Textarea
          id="agent-write-tools"
          className="mt-1 min-h-[56px] font-mono text-xs"
          placeholder={"update_appointment"}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            onChange(parseNameList(e.target.value));
          }}
        />
        <p className="mt-0.5 text-[10px] text-muted-foreground">
          {hasAssistant
            ? "We could not read this assistant's tools, so type the names of the tools it may use to make changes, one per line."
            : "Type the names of the tools it may use to make changes, one per line. Choose an assistant to pick from its tools instead."}
        </p>
      </div>
    );
  }
  const changing = tools.filter((t) => t.changes !== "no");
  if (changing.length === 0) {
    return (
      <p className="text-[11px] text-muted-foreground">
        This assistant has no tools that change data, so there is nothing to allow. Choose Suggest, or give the assistant a tool that makes the change.
      </p>
    );
  }
  const toggle = (name: string) =>
    onChange(allowed.includes(name) ? allowed.filter((n) => n !== name) : [...allowed, name]);
  return (
    <fieldset>
      <legend className="text-xs font-medium">Changes it may make</legend>
      <div className="mt-1 space-y-1">
        {changing.map((t) => (
          <label key={t.name} className="flex items-start gap-1.5 text-[11px]">
            <input type="checkbox" className="mt-0.5" checked={allowed.includes(t.name)} onChange={() => toggle(t.name)} />
            <span>
              <code className="font-mono">{t.name}</code>
              <span className="text-muted-foreground">{t.changes === "yes" ? " changes data" : " might change data"}</span>
            </span>
          </label>
        ))}
      </div>
      {allowed.filter((n) => !changing.some((t) => t.name === n)).length > 0 && (
        <p className="mt-1 text-[10px] text-muted-foreground">
          Also listed: {allowed.filter((n) => !changing.some((t) => t.name === n)).join(", ")}
        </p>
      )}
    </fieldset>
  );
}

// ---------------------------------------------------------------------------
// Numbers
// ---------------------------------------------------------------------------

/** A number box that only commits (clamped into its range) when the person is done typing, so "5" on the way to "500" is allowed. */
function LimitInput({
  id,
  label,
  limit,
  value,
  onCommit,
}: {
  id: string;
  label: string;
  limit: Exclude<LimitKey, "minConfidence">;
  value: number | undefined;
  onCommit: (n: number) => void;
}) {
  const spec = STEP_LIMITS[limit];
  const shown = value === undefined ? spec.default : value;
  const [text, setText] = useState(String(shown));
  useEffect(() => setText(String(shown)), [shown]);
  const commit = () => {
    const n = clampLimit(limit, text === "" ? spec.default : text);
    setText(String(n));
    if (n !== value) onCommit(n);
  };
  return (
    <div className="flex items-center justify-between gap-2">
      <Label className="text-xs" htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-muted-foreground">{spec.min.toLocaleString("en-US")} to {spec.max.toLocaleString("en-US")}</span>
        <Input
          id={id}
          type="number"
          className="h-7 w-24 text-xs"
          min={spec.min}
          max={spec.max}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => { if (e.key === "Enter") commit(); }}
        />
      </div>
    </div>
  );
}

function ConfidenceSlider({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  const v = clampLimit("minConfidence", value);
  return (
    <div>
      <div className="flex items-center justify-between">
        <Label className="text-xs" htmlFor="agent-min-confidence">How sure it must be</Label>
        <span className="text-xs font-semibold" data-testid="confidence-value">{Math.round(v * 100)}%</span>
      </div>
      <input
        id="agent-min-confidence"
        type="range"
        className="mt-1 w-full"
        min={STEP_LIMITS.minConfidence.min}
        max={STEP_LIMITS.minConfidence.max}
        step={0.05}
        value={v}
        onChange={(e) => onChange(clampLimit("minConfidence", e.target.value))}
      />
      <p className="text-[10px] text-muted-foreground">Below this, it only suggests and a person decides.</p>
    </div>
  );
}
