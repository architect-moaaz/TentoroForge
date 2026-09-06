"use client";

import { useState, useEffect } from "react";
import { X, Plus, FileText, Unlink, ChevronsUpDown, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
} from "@/components/ui/command";
import { useOrgEntities } from "@/hooks/useOrgEntities";
import { cn } from "@/lib/utils";
import { VariablePicker } from "./VariablePicker";
import { ConditionModeToggle } from "./ConditionModeToggle";
import {
  ACTION_FIELD_SPECS,
  ACTION_TYPE_KEYS,
  type FieldSpec,
} from "./actionFieldSpecs";
import { ACTION_CONTRACTS } from "./actionContracts";
import type { InputMapping, OutputMapping } from "./actionContracts";
import { InputMappingSection } from "./InputMappingSection";
import { OutputMappingSection } from "./OutputMappingSection";
import { useNodeContract } from "./useNodeContract";
import { collectWorkflowVariables } from "./workflowVariables";
import { NodeHistoryTab } from "./NodeHistoryTab";
import { DecisionNodeProps } from "./DecisionNodeProps";
import { NodeIOParamsEditor } from "./NodeIOParamsEditor";
import { asObjectList } from "./config-guards";
import type { NodeParam } from "@/types/workflow";
import { FormFieldEditor } from "./FormFieldEditor";
import { TriggerMappingEditor } from "./TriggerMappingEditor";
import { AssignmentStrategyEditor } from "./AssignmentStrategyEditor";
import { api } from "@/lib/api";
import type { AppModel } from "@/types/app-model";
import type { PageDefinition } from "@/types/ui-editor";
import type {
  WorkflowNodeData,
  WorkflowNodeConfig,
  WorkflowNodeSerialized,
  TriggerType,
  ActionType,
  AssignType,
  ApprovalType,
} from "@/types/workflow";

interface NodePropertiesPanelProps {
  nodeData: WorkflowNodeData;
  nodeId: string;
  allNodes: WorkflowNodeSerialized[];
  /** A2-2: needed so upstream is decided by the graph, not array order. */
  allEdges?: Array<{ source: string; target: string }>;
  appModel: AppModel | null;
  projectId?: string;
  orgId?: string;
  workflowId?: string;
  processVariables?: import("@/types/workflow").ProcessVariable[];
  onUpdate: (data: Partial<WorkflowNodeData>) => void;
  onClose: () => void;
}

export function NodePropertiesPanel({
  nodeData,
  nodeId,
  allNodes,
  allEdges,
  appModel,
  projectId,
  orgId,
  workflowId,
  processVariables,
  onUpdate,
  onClose,
}: NodePropertiesPanelProps) {
  const { label, nodeType, config } = nodeData;

  const updateConfig = (updates: Partial<WorkflowNodeConfig>) => {
    onUpdate({ config: { ...config, ...updates } });
  };

  const modelNames = appModel?.database?.tables?.map((t) => t.name) ?? [];

  const workflowVariables = collectWorkflowVariables({
    processVariables,
    appModel,
    nodes: allNodes,
    edges: allEdges,
    currentNodeId: nodeId,
  });

  const insertVariable = (variable: string) => {
    // Insert into the last focused input (simplified: append to description)
    const current = config.description || "";
    updateConfig({ description: current + variable });
  };

  return (
    <div className="flex w-[320px] shrink-0 flex-col border-l bg-white overflow-y-auto">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-xs font-semibold">Properties</span>
        {/* A10-1: icon-only buttons had no accessible name — axe `button-name`,
            critical. A screen reader announced them all as bare "button". */}
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose} aria-label="Close properties panel">
          <X className="h-3 w-3" />
        </Button>
      </div>

      <div className="space-y-4 p-3">
        {/* Common: Label */}
        <div>
          {/* A10-2: the visible <Label> was not ASSOCIATED with the input
              (no htmlFor/id), so axe reported a critical `label` violation and
              the panel's most important control was unlabelled for assistive
              tech. htmlFor + id links them. */}
          <Label className="text-xs" htmlFor="wf-node-label">Label</Label>
          <Input
            id="wf-node-label"
            className="mt-1 h-8 text-xs"
            value={label}
            onChange={(e) => onUpdate({ label: e.target.value })}
          />
        </div>

        <Separator />

        {/* Type-specific properties */}
        {nodeType === "trigger" && (
          <TriggerProps config={config} onUpdate={updateConfig} modelNames={modelNames} />
        )}
        {(nodeType === "action" ||
          nodeType === "ai_generate" ||
          nodeType === "ai_classify" ||
          nodeType === "ai_extract" ||
          nodeType === "ai_decide") && (
          <ActionProps
            // AI nodes carry their type in `nodeType`, not `config.actionType` —
            // seed it so the contract lookup finds the right entry. The
            // ActionType type union predates the AI-contract merge; cast
            // through unknown since the runtime dispatch table (ACTION_CONTRACTS)
            // now covers every ai_* key too.
            config={{
              ...config,
              actionType: (config.actionType || nodeType) as ActionType,
            }}
            appModel={appModel}
            variables={workflowVariables}
            nodeId={nodeId}
            orgId={orgId}
            onUpdate={updateConfig}
          />
        )}
        {(nodeType === "condition" || nodeType === "exclusive_gateway") && (
          <ConditionProps config={config} onUpdate={updateConfig} />
        )}
        {nodeType === "decision" && (
          <DecisionNodeProps config={config} onUpdate={updateConfig} />
        )}
        {nodeType === "wait" && (
          <WaitProps config={config} onUpdate={updateConfig} />
        )}
        {(nodeType === "assignment" || nodeType === "task_pool" || nodeType === "user_task") && (
          <AssignmentProps config={config} onUpdate={updateConfig} orgId={orgId} />
        )}
        {nodeType === "approval" && (
          <ApprovalProps config={config} onUpdate={updateConfig} orgId={orgId} />
        )}
        {nodeType === "escalation" && (
          <EscalationProps config={config} onUpdate={updateConfig} orgId={orgId} />
        )}
        {/* AI nodes (ai_generate / ai_classify / ai_extract / ai_decide)
             now render through the contract-driven ActionProps above so
             their input/output shape stays in sync with actionContracts.ts.
             The old flat-field AI*Props renderers below are kept for one
             release as a safety net; a runtime fallback would flip the
             above `||` chain back to the old branches. */}

        {/* Page linking for human-in-loop nodes */}
        {(nodeType === "assignment" || nodeType === "approval" || nodeType === "task_pool" || nodeType === "user_task") && projectId && (
          <>
            <Separator />
            <PageLinkSection
              projectId={projectId}
              config={config}
              onUpdate={updateConfig}
            />
          </>
        )}

        {/* --- Trigger input mapping: payload field → process variable.
             Same key-value mapper widget as the object-input editor; the
             value picker draws from the full variable set. --- */}
        {nodeType === "trigger" && (
          <>
            <Separator />
            <TriggerMappingEditor
              mapping={config.inputMapping || {}}
              processVariables={processVariables ?? []}
              variables={workflowVariables}
              onChange={(inputMapping) => updateConfig({ inputMapping })}
            />
          </>
        )}

        {/* --- Free-form I/O params for node types without a declared
             contract. Action nodes are handled by the contract-driven
             Input/Output Mapping sections above (see actionContracts.ts);
             showing both would double up on the same concept. --- */}
        {nodeType !== "trigger" &&
          nodeType !== "end" &&
          nodeType !== "action" &&
          nodeType !== "condition" &&
          nodeType !== "exclusive_gateway" &&
          nodeType !== "decision" &&
          nodeType !== "wait" &&
          nodeType !== "escalation" && (
          <>
            <Separator />
            <NodeIOParamsEditor
              inputParams={asObjectList<NodeParam>(config.inputParams)}
              outputParams={asObjectList<NodeParam>(config.outputParams)}
              processVariables={processVariables ?? []}
              onUpdateInputs={(inputParams) => updateConfig({ inputParams })}
              onUpdateOutputs={(outputParams) => updateConfig({ outputParams })}
            />
          </>
        )}

        {/* --- Form Binding (any human-in-loop node) --- */}
        {(nodeType === "approval" || nodeType === "assignment" || nodeType === "task_pool" || nodeType === "user_task") && (
          <>
            <Separator />
            <FormFieldEditor
              formBinding={config.formBinding || { title: "", fields: [] }}
              processVariables={[]}
              entityFields={modelNames}
              onChange={(formBinding) => updateConfig({ formBinding })}
            />
          </>
        )}

        {/* --- Assignment Strategy (any human-in-loop node) --- */}
        {(nodeType === "approval" || nodeType === "assignment" || nodeType === "task_pool" || nodeType === "user_task") && (
          <>
            <Separator />
            <AssignmentStrategyEditor
              assignment={config.assignment || { strategy: "role", value: "" }}
              onChange={(assignment) => updateConfig({ assignment })}
            />
          </>
        )}

        {nodeType === "action" && projectId && workflowId && (
          <>
            <Separator />
            <NodeHistoryTab
              projectId={projectId}
              workflowId={workflowId}
              nodeId={nodeId}
            />
          </>
        )}

        {nodeType !== "end" && (
          <>
            <Separator />
            <VariablePicker
              appModel={appModel}
              nodes={allNodes}
              currentNodeId={nodeId}
              processVariables={processVariables}
              onInsert={insertVariable}
            />
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Type-specific property forms
// ---------------------------------------------------------------------------

function TriggerProps({
  config,
  onUpdate,
  modelNames,
}: {
  config: WorkflowNodeConfig;
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
  modelNames: string[];
}) {
  const triggerType = config.type || "manual";
  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs">Trigger Type</Label>
        <Select
          value={triggerType}
          onValueChange={(v) => onUpdate({ type: v as TriggerType })}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="api_event" className="text-xs">API Event</SelectItem>
            <SelectItem value="schedule" className="text-xs">Schedule (Cron)</SelectItem>
            <SelectItem value="db_change" className="text-xs">DB Change</SelectItem>
            <SelectItem value="webhook" className="text-xs">Webhook</SelectItem>
            <SelectItem value="manual" className="text-xs">Manual</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {triggerType === "api_event" && (
        <div>
          <Label className="text-xs" htmlFor="wf-event-name">Event Name</Label>
          <Input
            id="wf-event-name"
            className="mt-1 h-8 text-xs"
            placeholder="e.g. expense.created"
            value={(config as Record<string, string | undefined>).event || ""}
            onChange={(e) => onUpdate({ ...config, event: e.target.value } as Partial<WorkflowNodeConfig>)}
          />
        </div>
      )}
      {triggerType === "schedule" && (
        <CronBuilder
          value={(config as Record<string, string | undefined>).cron || ""}
          onChange={(v) =>
            onUpdate({ ...config, cron: v } as Partial<WorkflowNodeConfig>)
          }
        />
      )}
      {triggerType === "db_change" && (
        <>
          <div>
            <Label className="text-xs">Model</Label>
            <Select
              value={config.model || ""}
              onValueChange={(v) => onUpdate({ model: v })}
            >
              <SelectTrigger className="mt-1 h-8 text-xs">
                <SelectValue placeholder="Select model..." />
              </SelectTrigger>
              <SelectContent>
                {modelNames.map((m) => (
                  <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs" htmlFor="wf-condition">Condition</Label>
            <Input
              id="wf-condition"
              className="mt-1 h-8 text-xs"
              placeholder="e.g. status changed to 'approved'"
              value={(config as Record<string, string | undefined>).condition || ""}
              onChange={(e) => onUpdate({ ...config, condition: e.target.value } as Partial<WorkflowNodeConfig>)}
            />
          </div>
        </>
      )}
      {triggerType === "webhook" && (
        <div>
          <Label className="text-xs" htmlFor="wf-webhook-path">Webhook Path</Label>
          <Input
            id="wf-webhook-path"
            className="mt-1 h-8 text-xs"
            placeholder="/api/webhooks/my-hook"
            value={(config as Record<string, string | undefined>).path || ""}
            onChange={(e) => onUpdate({ ...config, path: e.target.value } as Partial<WorkflowNodeConfig>)}
          />
        </div>
      )}
      {triggerType === "manual" && (
        <div>
          <Label className="text-xs" htmlFor="wf-button-label">Button Label</Label>
          <Input
            id="wf-button-label"
            className="mt-1 h-8 text-xs"
            placeholder="Start Workflow"
            value={(config as Record<string, string | undefined>).name || ""}
            onChange={(e) => onUpdate({ ...config, name: e.target.value } as Partial<WorkflowNodeConfig>)}
          />
        </div>
      )}
      <div>
        <Label className="text-xs" htmlFor="wf-description">Description</Label>
        <Input
          id="wf-description"
          className="mt-1 h-8 text-xs"
          placeholder="Describe when this triggers..."
          value={config.description || ""}
          onChange={(e) => onUpdate({ description: e.target.value })}
        />
      </div>
    </div>
  );
}

const CRON_PRESETS: { label: string; value: string }[] = [
  { label: "Every hour", value: "0 * * * *" },
  { label: "Every day at 9am", value: "0 9 * * *" },
  { label: "Every weekday at 9am", value: "0 9 * * MON-FRI" },
  { label: "Every Monday at 9am", value: "0 9 * * MON" },
  { label: "First of each month at 9am", value: "0 9 1 * *" },
];

function CronBuilder({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const knownPreset = CRON_PRESETS.find((p) => p.value === value);
  const [mode, setMode] = useState<"preset" | "custom">(
    knownPreset || !value ? "preset" : "custom",
  );

  return (
    <div className="space-y-2">
      <Label className="text-xs">When to run</Label>
      <Select
        value={mode === "custom" ? "__custom" : value}
        onValueChange={(v) => {
          if (v === "__custom") {
            setMode("custom");
          } else {
            setMode("preset");
            onChange(v);
          }
        }}
      >
        <SelectTrigger className="h-8 text-xs">
          <SelectValue placeholder="Pick a schedule…" />
        </SelectTrigger>
        <SelectContent>
          {CRON_PRESETS.map((p) => (
            <SelectItem key={p.value} value={p.value} className="text-xs">
              {p.label}
            </SelectItem>
          ))}
          <SelectItem value="__custom" className="text-xs">
            Custom (cron expression)
          </SelectItem>
        </SelectContent>
      </Select>
      {mode === "custom" && (
        <div>
          <Input
            className="h-8 text-xs font-mono"
            placeholder="0 9 * * MON"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
          <p className="mt-1 text-[10px] text-muted-foreground">
            Format: minute hour day-of-month month day-of-week (e.g.{" "}
            <code>0 9 * * MON</code> = Mondays at 9am UTC).
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * Renders the Properties panel for an action node from ACTION_CONTRACTS
 * (per docs/superpowers/specs/2026-07-22-workflow-node-contracts.md).
 *
 * The contract declares INPUTS and OUTPUTS. The panel:
 *   1. Shows an action-type dropdown, sourced from the contract keys.
 *   2. Renders an Input Mapping section: one row per declared input,
 *      with a variable/literal/expression source picker per row.
 *   3. Renders an Output Mapping section: every declared output with
 *      an opt-in "promote to process variable" affordance.
 *
 * Legacy actions that don't yet have a contract fall back to the old
 * flat-fields renderer (actionFieldSpecs.ts). At present every action
 * has a contract, but the fallback keeps the panel robust if the palette
 * grows before the catalog catches up.
 */
function ActionProps({
  config,
  appModel,
  variables,
  nodeId,
  orgId,
  onUpdate,
}: {
  config: WorkflowNodeConfig;
  appModel: AppModel | null;
  variables: import("./workflowVariables").WorkflowVariable[];
  nodeId: string;
  orgId?: string;
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
}) {
  const actionType = (config.actionType as string) || "custom";
  const contract = useNodeContract(config, appModel);
  const legacySpec = ACTION_FIELD_SPECS[actionType];

  const setInputMappings = (mappings: InputMapping[]) =>
    onUpdate({ inputMappings: mappings });
  const setOutputMappings = (mappings: OutputMapping[]) =>
    onUpdate({ outputMappings: mappings });

  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs">Action Type</Label>
        <Select
          value={actionType}
          onValueChange={(v) => onUpdate({ actionType: v as ActionType })}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.keys(ACTION_CONTRACTS).map((k) => (
              <SelectItem key={k} value={k} className="text-xs">
                {ACTION_CONTRACTS[k].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label className="text-xs" htmlFor="wf-description">Description</Label>
        <Input
          id="wf-description"
          className="mt-1 h-8 text-xs"
          placeholder="Describe what this action does..."
          value={config.description || ""}
          onChange={(e) => onUpdate({ description: e.target.value })}
        />
      </div>

      {contract ? (
        <>
          <Separator />
          <InputMappingSection
            contract={contract}
            config={config}
            variables={variables}
            appModel={appModel}
            orgId={orgId}
            onChange={setInputMappings}
          />
          <Separator />
          <OutputMappingSection
            contract={contract}
            nodeId={nodeId}
            outputMappings={asObjectList<OutputMapping>(config.outputMappings)}
            onChange={setOutputMappings}
          />
        </>
      ) : legacySpec ? (
        legacySpec.fields.map((f) => (
          <ActionFieldControl
            key={f.key}
            field={f}
            value={(config as Record<string, unknown>)[f.key]}
            onChange={(v) => onUpdate({ [f.key]: v } as Partial<WorkflowNodeConfig>)}
          />
        ))
      ) : (
        <div className="rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
          No contract for action type <code>{actionType}</code>. Add an entry
          to <code className="ml-1">actionContracts.ts</code>.
        </div>
      )}
    </div>
  );
}

/**
 * One control per FieldSpec. Handles the four kinds:
 *   text     → <Input>
 *   textarea → <Textarea>
 *   select   → <Select> with spec.options
 *   json     → <Textarea> that stores a JSON string; parses on blur.
 *              Local state so the user can type invalid JSON without
 *              being interrupted; the parsed value only propagates when
 *              JSON.parse succeeds.
 */
function ActionFieldControl({
  field,
  value,
  onChange,
}: {
  field: FieldSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  // JSON kinds hold their raw text in local state so intermediate keystrokes
  // don't fight the caller's onChange (which only wants parsed values).
  const [jsonText, setJsonText] = useState<string>(() =>
    field.kind === "json"
      ? value === undefined
        ? ""
        : typeof value === "string"
          ? value
          : JSON.stringify(value, null, 2)
      : "",
  );
  const [jsonError, setJsonError] = useState<string | null>(null);

  useEffect(() => {
    if (field.kind !== "json") return;
    // Reflect external changes (e.g. undo) back into local state without
    // clobbering while the user is actively editing.
    const external =
      value === undefined
        ? ""
        : typeof value === "string"
          ? value
          : JSON.stringify(value, null, 2);
    if (external !== jsonText && document.activeElement?.tagName !== "TEXTAREA") {
      setJsonText(external);
      setJsonError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, field.kind]);

  const label = (
    <Label className="text-xs">{field.label}</Label>
  );
  const help = field.help ? (
    <p className="mt-1 text-[10px] text-muted-foreground">{field.help}</p>
  ) : null;

  if (field.kind === "select" && field.options) {
    return (
      <div>
        {label}
        <Select
          value={(typeof value === "string" ? value : "") || field.options[0]}
          onValueChange={(v) => onChange(v)}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {field.options.map((opt) => (
              <SelectItem key={opt} value={opt} className="text-xs">
                {opt}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {help}
      </div>
    );
  }

  if (field.kind === "textarea") {
    return (
      <div>
        {label}
        <Textarea
          className="mt-1 text-xs font-mono min-h-[80px]"
          placeholder={field.placeholder}
          value={(typeof value === "string" ? value : "") || ""}
          onChange={(e) => onChange(e.target.value)}
        />
        {help}
      </div>
    );
  }

  if (field.kind === "json") {
    return (
      <div>
        {label}
        <Textarea
          className={cn(
            "mt-1 text-xs font-mono min-h-[100px]",
            jsonError && "border-red-500",
          )}
          placeholder={field.placeholder}
          value={jsonText}
          onChange={(e) => {
            setJsonText(e.target.value);
            setJsonError(null);
          }}
          onBlur={() => {
            const t = jsonText.trim();
            if (t === "") {
              // Blank → clear the underlying value entirely.
              setJsonError(null);
              onChange(undefined);
              return;
            }
            try {
              const parsed = JSON.parse(t);
              setJsonError(null);
              onChange(parsed);
            } catch (err) {
              setJsonError((err as Error).message);
            }
          }}
        />
        {jsonError ? (
          <p className="mt-1 text-[10px] text-red-600 font-mono">
            Invalid JSON: {jsonError}
          </p>
        ) : (
          help
        )}
      </div>
    );
  }

  // Default: plain text input.
  return (
    <div>
      {label}
      <Input
        className="mt-1 h-8 text-xs"
        placeholder={field.placeholder}
        value={(typeof value === "string" ? value : "") || ""}
        onChange={(e) => onChange(e.target.value)}
      />
      {help}
    </div>
  );
}

function ConditionProps({
  config,
  onUpdate,
}: {
  config: WorkflowNodeConfig;
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
}) {
  const mode = config.conditionMode || "expression";
  const fields = ["trigger.amount", "trigger.status", "trigger.type", "previous.output"];

  return (
    <div className="space-y-3">
      <ConditionModeToggle
        mode={mode}
        onModeChange={(m) => onUpdate({ conditionMode: m })}
        conditionTree={config.conditionTree ?? null}
        onConditionTreeChange={(tree) => onUpdate({ conditionTree: tree })}
        fields={fields}
        expression={config.expression || ""}
        onExpressionChange={(expr) => onUpdate({ expression: expr })}
      />
    </div>
  );
}

function WaitProps({
  config,
  onUpdate,
}: {
  config: WorkflowNodeConfig;
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
}) {
  const UNITS = [
    { key: "ms", label: "milliseconds", ms: 1 },
    { key: "s", label: "seconds", ms: 1_000 },
    { key: "min", label: "minutes", ms: 60_000 },
    { key: "h", label: "hours", ms: 3_600_000 },
    { key: "d", label: "days", ms: 86_400_000 },
  ] as const;

  const rawMs = Number(config.duration ?? 0) || 0;
  const unit =
    UNITS.slice().reverse().find((u) => rawMs > 0 && rawMs % u.ms === 0) ??
    UNITS[1];
  const amount = rawMs > 0 ? rawMs / unit.ms : "";
  const setDuration = (n: number | "", unitKey: string) => {
    const u = UNITS.find((u) => u.key === unitKey) ?? UNITS[1];
    const ms = n === "" ? 0 : Math.max(0, Math.round(Number(n) * u.ms));
    onUpdate({ duration: String(ms) });
  };

  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs">Wait for</Label>
        <div className="mt-1 flex items-center gap-2">
          <Input
            type="number"
            min={0}
            className="h-8 w-20 text-xs"
            value={amount}
            onChange={(e) => {
              const v = e.target.value === "" ? "" : Number(e.target.value);
              setDuration(v, unit.key);
            }}
          />
          <Select value={unit.key} onValueChange={(k) => setDuration(amount === "" ? 0 : amount, k)}>
            <SelectTrigger className="h-8 flex-1 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {UNITS.map((u) => (
                <SelectItem key={u.key} value={u.key} className="text-xs">
                  {u.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <p className="mt-1 text-[10px] text-muted-foreground">
          Waits capped at 5 seconds during in-editor runs; live workflows honor
          the full time.
        </p>
      </div>
    </div>
  );
}

/** Searchable combobox for org entities (roles, groups, people, etc.) */
function OrgEntityCombobox({
  orgId,
  assignType,
  value,
  valueName,
  onSelect,
}: {
  orgId?: string;
  assignType: AssignType;
  value?: string;
  valueName?: string;
  onSelect: (id: string, label: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const { options, isLoading } = useOrgEntities(orgId, assignType);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="mt-1 h-8 w-full justify-between text-xs font-normal"
        >
          <span className="truncate">
            {valueName || value || `Select ${assignType}...`}
          </span>
          <ChevronsUpDown className="ml-1 h-3 w-3 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[248px] p-0" align="start">
        <Command>
          <CommandInput placeholder={`Search ${assignType}...`} className="h-8 text-xs" />
          <CommandList>
            <CommandEmpty>
              {isLoading ? (
                <span className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" /> Loading...
                </span>
              ) : (
                "No results found."
              )}
            </CommandEmpty>
            <CommandGroup>
              {options.map((opt) => (
                <CommandItem
                  key={opt.id}
                  value={opt.label}
                  onSelect={() => {
                    onSelect(opt.id, opt.label);
                    setOpen(false);
                  }}
                  className="text-xs"
                >
                  <Check
                    className={cn(
                      "mr-2 h-3 w-3",
                      value === opt.id ? "opacity-100" : "opacity-0",
                    )}
                  />
                  {opt.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

const AUTO_RESOLVE_TYPES = ["manager_of_requester", "department_head", "initiator"] as const;
const ENTITY_TYPES = ["role", "group", "department", "person", "team"] as const;

function AssignmentProps({
  config,
  onUpdate,
  orgId,
}: {
  config: WorkflowNodeConfig;
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
  orgId?: string;
}) {
  const assignType = config.assignType || "role";
  const isEntityType = (ENTITY_TYPES as readonly string[]).includes(assignType);
  const isAutoResolve = (AUTO_RESOLVE_TYPES as readonly string[]).includes(assignType);
  const isProcessVariable = assignType === "process_variable";

  const handleTypeChange = (v: string) => {
    onUpdate({
      assignType: v as AssignType,
      assignTarget: undefined,
      assignTargetName: undefined,
      assignVariablePath: undefined,
    });
  };

  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs">Assign To</Label>
        <Select
          value={assignType}
          onValueChange={handleTypeChange}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel className="text-[10px] text-muted-foreground">Org Chart</SelectLabel>
              <SelectItem value="role" className="text-xs">Role</SelectItem>
              <SelectItem value="group" className="text-xs">Group</SelectItem>
              <SelectItem value="department" className="text-xs">Department</SelectItem>
              <SelectItem value="team" className="text-xs">Team</SelectItem>
              <SelectItem value="person" className="text-xs">Specific Person</SelectItem>
            </SelectGroup>
            <SelectGroup>
              <SelectLabel className="text-[10px] text-muted-foreground">Dynamic</SelectLabel>
              <SelectItem value="manager_of_requester" className="text-xs">Requester&apos;s Manager</SelectItem>
              <SelectItem value="department_head" className="text-xs">Department Head</SelectItem>
              <SelectItem value="initiator" className="text-xs">Workflow Initiator</SelectItem>
            </SelectGroup>
            <SelectGroup>
              <SelectLabel className="text-[10px] text-muted-foreground">Variable</SelectLabel>
              <SelectItem value="process_variable" className="text-xs">Process Variable</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      {isEntityType && (
        <div>
          <Label className="text-xs">Target</Label>
          <OrgEntityCombobox
            orgId={orgId}
            assignType={assignType as AssignType}
            value={config.assignTarget}
            valueName={config.assignTargetName}
            onSelect={(id, label) => onUpdate({ assignTarget: id, assignTargetName: label })}
          />
        </div>
      )}
      {isAutoResolve && (
        <p className="text-[10px] text-muted-foreground mt-1">
          {assignType === "initiator"
            ? "Automatically assigned to the person who started the workflow."
            : assignType === "manager_of_requester"
              ? "Automatically assigned to the requester\u2019s manager at runtime."
              : "Automatically assigned to the requester\u2019s department head at runtime."}
        </p>
      )}
      {isProcessVariable && (
        <div>
          <Label className="text-xs" htmlFor="wf-variable-path">Variable Path</Label>
          <Input
            id="wf-variable-path"
            className="mt-1 h-8 text-xs font-mono"
            placeholder="{{trigger.assigned_person_id}}"
            value={config.assignVariablePath || ""}
            onChange={(e) => onUpdate({ assignVariablePath: e.target.value })}
          />
          <p className="text-[10px] text-muted-foreground mt-1">
            Person ID resolved from a workflow variable at runtime.
          </p>
        </div>
      )}
      <div>
        <Label className="text-xs" htmlFor="wf-sla-hours">SLA (hours)</Label>
        <Input
          id="wf-sla-hours"
          className="mt-1 h-8 text-xs"
          type="number"
          placeholder="e.g. 24"
          value={config.slaHours || ""}
          onChange={(e) => onUpdate({ slaHours: e.target.value ? parseInt(e.target.value) : undefined })}
        />
      </div>
      <div>
        <Label className="text-xs" htmlFor="wf-description">Description</Label>
        <Input
          id="wf-description"
          className="mt-1 h-8 text-xs"
          placeholder="Task description..."
          value={config.description || ""}
          onChange={(e) => onUpdate({ description: e.target.value })}
        />
      </div>
    </div>
  );
}

function ApprovalProps({
  config,
  onUpdate,
  orgId,
}: {
  config: WorkflowNodeConfig;
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
  orgId?: string;
}) {
  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs">Approval Type</Label>
        <Select
          value={config.approvalType || "single"}
          onValueChange={(v) => onUpdate({ approvalType: v as ApprovalType })}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="single" className="text-xs">Single Approver</SelectItem>
            <SelectItem value="sequential" className="text-xs">Sequential Chain</SelectItem>
            <SelectItem value="parallel_all" className="text-xs">Parallel (All)</SelectItem>
            <SelectItem value="parallel_any" className="text-xs">Parallel (Any)</SelectItem>
            <SelectItem value="threshold" className="text-xs">Threshold</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {config.approvalType === "threshold" && (
        <div>
          <Label className="text-xs" htmlFor="wf-required-approvals">Required Approvals</Label>
          <Input
            id="wf-required-approvals"
            className="mt-1 h-8 text-xs"
            type="number"
            placeholder="e.g. 3"
            value={config.requiredApprovals || ""}
            onChange={(e) => onUpdate({ requiredApprovals: parseInt(e.target.value) || undefined })}
          />
        </div>
      )}
      <AssignmentProps config={config} onUpdate={onUpdate} orgId={orgId} />
    </div>
  );
}

function EscalationProps({
  config,
  onUpdate,
  orgId,
}: {
  config: WorkflowNodeConfig;
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
  orgId?: string;
}) {
  const [assignType, setAssignType] = useState<AssignType>(
    (config as { escalateAssignType?: AssignType }).escalateAssignType || "role",
  );
  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs">Escalate after</Label>
        <div className="mt-1 flex items-center gap-2">
          <Input
            className="h-8 w-20 text-xs"
            type="number"
            min={1}
            placeholder="24"
            value={config.slaHours || ""}
            onChange={(e) => onUpdate({ slaHours: e.target.value ? parseInt(e.target.value) : undefined })}
          />
          <span className="text-xs text-muted-foreground">hours</span>
        </div>
      </div>
      <div>
        <Label className="text-xs">Escalate to</Label>
        <Select
          value={assignType}
          onValueChange={(v) => {
            const next = v as AssignType;
            setAssignType(next);
            // Persist the type immediately and drop the now-mismatched target.
            // Previously the type was saved ONLY when an entity was (re)picked,
            // so changing Role→Person without re-selecting left escalateAssignType
            // stale and escalateTo pointing at the wrong entity kind on reopen.
            onUpdate({
              escalateAssignType: next,
              escalateTo: undefined,
              escalateToName: undefined,
            } as Partial<WorkflowNodeConfig>);
          }}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="role" className="text-xs">A role</SelectItem>
            <SelectItem value="person" className="text-xs">A specific person</SelectItem>
            <SelectItem value="group" className="text-xs">A group</SelectItem>
            <SelectItem value="department" className="text-xs">A department</SelectItem>
          </SelectContent>
        </Select>
        <OrgEntityCombobox
          orgId={orgId}
          assignType={assignType}
          value={config.escalateTo}
          valueName={config.escalateToName}
          onSelect={(id, label) =>
            onUpdate({
              escalateTo: id,
              escalateToName: label,
              escalateAssignType: assignType,
            } as Partial<WorkflowNodeConfig>)
          }
        />
      </div>
      <div>
        <Label className="text-xs" htmlFor="wf-description">Description</Label>
        <Input
          id="wf-description"
          className="mt-1 h-8 text-xs"
          placeholder="Why is this escalation needed?"
          value={config.description || ""}
          onChange={(e) => onUpdate({ description: e.target.value })}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AI Node property forms
// ---------------------------------------------------------------------------

function AIClassifyProps({
  config,
  onUpdate,
}: {
  config: WorkflowNodeConfig;
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
}) {
  const labels = config.aiLabels || [];
  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs" htmlFor="wf-input-variable">Input Variable</Label>
        <Input
          id="wf-input-variable"
          className="mt-1 h-8 text-xs font-mono"
          placeholder="{{trigger.body}}"
          value={config.aiInput || ""}
          onChange={(e) => onUpdate({ aiInput: e.target.value })}
        />
      </div>
      <div>
        <Label className="text-xs">Classification Labels</Label>
        <div className="mt-1 space-y-1">
          {labels.map((label, i) => (
            <div key={i} className="flex gap-1">
              <Input
                className="h-7 text-xs flex-1"
                placeholder={`Label ${i + 1}`}
                value={label}
                onChange={(e) => {
                  const updated = [...labels];
                  updated[i] = e.target.value;
                  onUpdate({ aiLabels: updated });
                }}
              />
              <Button
                aria-label="Remove"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => onUpdate({ aiLabels: labels.filter((_, j) => j !== i) })}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => onUpdate({ aiLabels: [...labels, ""] })}
          >
            <Plus className="h-3 w-3 mr-1" />
            Add Label
          </Button>
        </div>
      </div>
      <div>
        <Label className="text-xs" htmlFor="wf-confidence-threshold">Confidence Threshold</Label>
        <Input
          id="wf-confidence-threshold"
          className="mt-1 h-8 text-xs"
          type="number"
          step="0.1"
          min="0"
          max="1"
          placeholder="0.7"
          value={config.aiConfidenceThreshold ?? ""}
          onChange={(e) => onUpdate({ aiConfidenceThreshold: e.target.value ? parseFloat(e.target.value) : undefined })}
        />
      </div>
      <div>
        <Label className="text-xs" htmlFor="wf-custom-prompt-optional">Custom Prompt (optional)</Label>
        <Textarea
          id="wf-custom-prompt-optional"
          className="mt-1 text-xs min-h-[50px]"
          placeholder="Additional instructions..."
          value={config.aiPrompt || ""}
          onChange={(e) => onUpdate({ aiPrompt: e.target.value })}
        />
      </div>
    </div>
  );
}

function AIExtractProps({
  config,
  onUpdate,
}: {
  config: WorkflowNodeConfig;
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
}) {
  const fields = config.aiExtractFields || [];
  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs" htmlFor="wf-input-variable">Input Variable</Label>
        <Input
          id="wf-input-variable"
          className="mt-1 h-8 text-xs font-mono"
          placeholder="{{trigger.text}}"
          value={config.aiInput || ""}
          onChange={(e) => onUpdate({ aiInput: e.target.value })}
        />
      </div>
      <div>
        <Label className="text-xs" htmlFor="wf-uploaded-file-optional">Uploaded File (optional)</Label>
        <Input
          id="wf-uploaded-file-optional"
          className="mt-1 h-8 text-xs font-mono"
          placeholder="{{input.fileId}}"
          value={config.aiFileRef || ""}
          onChange={(e) => onUpdate({ aiFileRef: e.target.value })}
        />
        <p className="mt-0.5 text-[10px] text-muted-foreground">
          Reference an uploaded file id to extract from a PDF/image (read natively by Claude).
        </p>
      </div>
      <div>
        <Label className="text-xs">Fields to Extract</Label>
        <div className="mt-1 space-y-1">
          {fields.map((field, i) => (
            <div key={i} className="flex gap-1">
              <Input
                className="h-7 text-xs flex-1"
                placeholder="Field name"
                value={field.name}
                onChange={(e) => {
                  const updated = [...fields];
                  updated[i] = { ...field, name: e.target.value };
                  onUpdate({ aiExtractFields: updated });
                }}
              />
              <Input
                className="h-7 text-xs w-20"
                placeholder="Type"
                value={field.type}
                onChange={(e) => {
                  const updated = [...fields];
                  updated[i] = { ...field, type: e.target.value };
                  onUpdate({ aiExtractFields: updated });
                }}
              />
              <Button
                aria-label="Remove"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => onUpdate({ aiExtractFields: fields.filter((_, j) => j !== i) })}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => onUpdate({ aiExtractFields: [...fields, { name: "", type: "string" }] })}
          >
            <Plus className="h-3 w-3 mr-1" />
            Add Field
          </Button>
        </div>
      </div>
      <div>
        <Label className="text-xs" htmlFor="wf-custom-prompt-optional-2">Custom Prompt (optional)</Label>
        <Textarea
          id="wf-custom-prompt-optional-2"
          className="mt-1 text-xs min-h-[50px]"
          placeholder="Additional instructions..."
          value={config.aiPrompt || ""}
          onChange={(e) => onUpdate({ aiPrompt: e.target.value })}
        />
      </div>
    </div>
  );
}

function AIDecideProps({
  config,
  onUpdate,
}: {
  config: WorkflowNodeConfig;
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
}) {
  const options = config.aiOptions || [];
  const rules = config.aiRules || [];
  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs" htmlFor="wf-decision-prompt">Decision Prompt</Label>
        <Textarea
          id="wf-decision-prompt"
          className="mt-1 text-xs min-h-[50px]"
          placeholder="What decision should the AI make?"
          value={config.aiPrompt || ""}
          onChange={(e) => onUpdate({ aiPrompt: e.target.value })}
        />
      </div>
      <div>
        <Label className="text-xs" htmlFor="wf-context-variable">Context Variable</Label>
        <Input
          id="wf-context-variable"
          className="mt-1 h-8 text-xs font-mono"
          placeholder="{{trigger.data}}"
          value={config.aiContext || ""}
          onChange={(e) => onUpdate({ aiContext: e.target.value })}
        />
      </div>
      <div>
        <Label className="text-xs">Decision Options</Label>
        <div className="mt-1 space-y-1">
          {options.map((opt, i) => (
            <div key={i} className="flex gap-1">
              <Input
                className="h-7 text-xs flex-1"
                placeholder={`Option ${i + 1}`}
                value={opt}
                onChange={(e) => {
                  const updated = [...options];
                  updated[i] = e.target.value;
                  onUpdate({ aiOptions: updated });
                }}
              />
              <Button
                aria-label="Remove"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => onUpdate({ aiOptions: options.filter((_, j) => j !== i) })}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => onUpdate({ aiOptions: [...options, ""] })}
          >
            <Plus className="h-3 w-3 mr-1" />
            Add Option
          </Button>
        </div>
      </div>
      <div>
        <Label className="text-xs">Decision Rules (optional)</Label>
        <div className="mt-1 space-y-1">
          {rules.map((rule, i) => (
            <div key={i} className="flex gap-1">
              <Input
                className="h-7 text-xs flex-1"
                placeholder="Rule description..."
                value={rule}
                onChange={(e) => {
                  const updated = [...rules];
                  updated[i] = e.target.value;
                  onUpdate({ aiRules: updated });
                }}
              />
              <Button
                aria-label="Remove"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => onUpdate({ aiRules: rules.filter((_, j) => j !== i) })}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => onUpdate({ aiRules: [...rules, ""] })}
          >
            <Plus className="h-3 w-3 mr-1" />
            Add Rule
          </Button>
        </div>
      </div>
      <p className="text-[10px] text-muted-foreground">
        Primary decision exits right. Alternative exits bottom.
      </p>
    </div>
  );
}

function AIGenerateProps({
  config,
  onUpdate,
}: {
  config: WorkflowNodeConfig;
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
}) {
  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs" htmlFor="wf-generation-prompt">Generation Prompt</Label>
        <Textarea
          id="wf-generation-prompt"
          className="mt-1 text-xs min-h-[60px]"
          placeholder="What should the AI generate?"
          value={config.aiPrompt || ""}
          onChange={(e) => onUpdate({ aiPrompt: e.target.value })}
        />
      </div>
      <div>
        <Label className="text-xs" htmlFor="wf-context-variable">Context Variable</Label>
        <Input
          id="wf-context-variable"
          className="mt-1 h-8 text-xs font-mono"
          placeholder="{{trigger.data}}"
          value={config.aiContext || ""}
          onChange={(e) => onUpdate({ aiContext: e.target.value })}
        />
      </div>
      <div>
        <Label className="text-xs" htmlFor="wf-tone">Tone</Label>
        <Input
          id="wf-tone"
          className="mt-1 h-8 text-xs"
          placeholder="e.g. professional, friendly, concise"
          value={config.aiTone || ""}
          onChange={(e) => onUpdate({ aiTone: e.target.value })}
        />
      </div>
      <div>
        <Label className="text-xs" htmlFor="wf-max-length-words">Max Length (words)</Label>
        <Input
          id="wf-max-length-words"
          className="mt-1 h-8 text-xs"
          type="number"
          placeholder="300"
          value={config.aiMaxLength || ""}
          onChange={(e) => onUpdate({ aiMaxLength: e.target.value ? parseInt(e.target.value) : undefined })}
        />
      </div>
      <div>
        <Label className="text-xs" htmlFor="wf-description">Description</Label>
        <Input
          id="wf-description"
          className="mt-1 h-8 text-xs"
          placeholder="What is generated..."
          value={config.description || ""}
          onChange={(e) => onUpdate({ description: e.target.value })}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page linking section for human-in-loop nodes
// ---------------------------------------------------------------------------

function PageLinkSection({
  projectId,
  config,
  onUpdate,
}: {
  projectId: string;
  config: WorkflowNodeConfig;
  onUpdate: (c: Partial<WorkflowNodeConfig>) => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pages, setPages] = useState<PageDefinition[]>([]);
  const [loadingPages, setLoadingPages] = useState(false);

  useEffect(() => {
    if (pickerOpen) {
      setLoadingPages(true);
      api
        .get<PageDefinition[]>(`/api/projects/${projectId}/pages`)
        .then(setPages)
        .finally(() => setLoadingPages(false));
    }
  }, [pickerOpen, projectId]);

  return (
    <div className="space-y-2">
      <span className="text-xs font-semibold">Linked Page</span>
      {config.pageId ? (
        <div className="flex items-center gap-2 rounded border bg-muted/30 p-2">
          <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs flex-1 truncate">
            {config.pageName || config.pageId}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => onUpdate({ pageId: undefined, pageName: undefined })}
            title="Unlink page"
          >
            <Unlink className="h-3 w-3" />
          </Button>
        </div>
      ) : (
        <p className="text-[10px] text-muted-foreground">No page linked</p>
      )}
      <Button
        variant="outline"
        size="sm"
        className="h-7 text-xs w-full"
        onClick={() => setPickerOpen(true)}
      >
        <FileText className="h-3 w-3 mr-1" />
        {config.pageId ? "Change Page" : "Link Page"}
      </Button>

      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-sm">Select a Page</DialogTitle>
          </DialogHeader>
          <div className="max-h-60 overflow-y-auto divide-y">
            {loadingPages ? (
              <p className="text-xs text-muted-foreground py-4 text-center">
                Loading...
              </p>
            ) : pages.length === 0 ? (
              <p className="text-xs text-muted-foreground py-4 text-center">
                No pages available. Create a page in the Design tab first.
              </p>
            ) : (
              pages.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center gap-2 px-2 py-2 hover:bg-muted/30 cursor-pointer rounded"
                  onClick={() => {
                    onUpdate({ pageId: p.id, pageName: p.name });
                    setPickerOpen(false);
                  }}
                >
                  <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  <div className="min-w-0 flex-1">
                    <span className="text-xs font-medium">{p.name}</span>
                    <p className="text-[10px] text-muted-foreground truncate">
                      {p.route}
                    </p>
                  </div>
                </div>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
