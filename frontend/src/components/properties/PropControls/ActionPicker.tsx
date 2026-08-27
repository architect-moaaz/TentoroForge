"use client";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import * as React from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

type ActionType = "none" | "navigate" | "workflow" | "submitForm" | "openModal";

interface ActionValue {
  action?: string;
  type?: string;
  trigger?: string;
  to?: string;
  workflow?: string;
  target?: string;
  modal?: string;
  params?: Record<string, unknown>;
  /** Workflow dispatch payload — keys are the workflow's declared input
   *  names, values are literals or `{{expr}}` templates. Button consumes
   *  this as its `args` prop (see packages/library/src/components/Button/Button.tsx). */
  args?: Record<string, unknown>;
}

interface WorkflowSchema {
  id: string;
  name: string;
  description: string;
  trigger: string;
  inputs: Array<{ name: string; type?: string }>;
}

export interface ActionPickerProps {
  label: string;
  value: any;
  onChange: (v: any) => void;
}

function detectActionType(v: any): ActionType {
  if (!v || typeof v !== "object") return "none";
  const t = v.action ?? v.type;
  if (t === "navigate") return "navigate";
  if (t === "workflow") return "workflow";
  if (t === "submitForm") return "submitForm";
  if (t === "openModal") return "openModal";
  return "none";
}

function emptyForType(t: ActionType): any {
  switch (t) {
    case "none": return null;
    case "navigate": return { action: "navigate", trigger: "" };
    case "workflow": return { action: "workflow", workflow: "", args: {} };
    case "submitForm": return { action: "submitForm", target: "" };
    case "openModal": return { action: "openModal", modal: "" };
  }
}

function useNavTransitions(projectId?: string): Array<{ id: string; trigger: string; from?: string; to?: string }> {
  const { data } = useQuery({
    queryKey: ["nav-flow-transitions", projectId],
    queryFn: async () => {
      if (!projectId) return { transitions: [] };
      const r = await fetch(`${API}/api/_debug/project-file/${projectId}/src/contracts/nav-flow.json`);
      return r.ok ? r.json() : { transitions: [] };
    },
    enabled: !!projectId,
  });
  return (data as any)?.transitions ?? [];
}

function useRegistryWorkflows(projectId?: string): { workflows: WorkflowSchema[]; loading: boolean } {
  const { data, isLoading } = useQuery({
    queryKey: ["registry-workflows", projectId],
    queryFn: async () => {
      if (!projectId) return [] as WorkflowSchema[];
      const r = await fetch(`${API}/api/projects/${projectId}/registry/workflows`);
      if (!r.ok) return [] as WorkflowSchema[];
      const rows = await r.json();
      return Array.isArray(rows) ? (rows as WorkflowSchema[]) : [];
    },
    enabled: !!projectId,
    staleTime: 30_000,
  });
  return { workflows: data ?? [], loading: isLoading };
}

const labelCls = "flex flex-col gap-1 text-sm";
const labelTextCls = "text-xs uppercase tracking-wide text-muted-foreground";
const inputCls = "border rounded px-2 py-1 text-sm bg-background w-full";

export function ActionPicker({ label, value, onChange }: ActionPickerProps) {
  const params = useParams();
  const projectId = params?.projectId as string | undefined;

  const type = detectActionType(value);
  const v = (value ?? {}) as ActionValue;
  const transitions = useNavTransitions(projectId);
  const { workflows, loading: workflowsLoading } = useRegistryWorkflows(projectId);
  const selectedWorkflow = workflows.find(
    (w) => w.id === v.workflow || w.name === v.workflow,
  );

  const setType = (t: ActionType) => onChange(emptyForType(t));

  const setArg = (inputName: string, argValue: string) => {
    const nextArgs = { ...(v.args ?? {}) };
    if (argValue === "") {
      delete nextArgs[inputName];
    } else {
      nextArgs[inputName] = argValue;
    }
    onChange({ ...v, args: nextArgs });
  };

  return (
    <div className="space-y-2 border rounded p-2 bg-background">
      <label className={labelCls}>
        <span className={labelTextCls}>{label}</span>
        <select
          className={inputCls}
          value={type}
          onChange={e => setType(e.target.value as ActionType)}
        >
          <option value="none">(no action)</option>
          <option value="navigate">Navigate</option>
          <option value="workflow">Run workflow</option>
          <option value="submitForm">Submit form</option>
          <option value="openModal">Open modal</option>
        </select>
      </label>

      {type === "navigate" && (
        <>
          <label className={labelCls}>
            <span className={labelTextCls}>Trigger</span>
            {transitions.length > 0 ? (
              <select
                className={inputCls}
                value={v.trigger ?? ""}
                onChange={e => onChange({ ...v, trigger: e.target.value })}
              >
                <option value="">— select transition —</option>
                {transitions.map((t: any) => (
                  <option key={t.id} value={t.trigger}>
                    {t.trigger} {t.from ? `(${t.from} → ${t.to})` : ""}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                className={inputCls}
                value={v.trigger ?? ""}
                placeholder="trigger name (no nav-flow.json found)"
                onChange={e => onChange({ ...v, trigger: e.target.value })}
              />
            )}
          </label>
        </>
      )}

      {type === "workflow" && (
        <>
          <label className={labelCls}>
            <span className={labelTextCls}>Workflow</span>
            {workflowsLoading ? (
              <div className="text-xs text-muted-foreground italic px-2 py-1">
                Loading workflows…
              </div>
            ) : workflows.length > 0 ? (
              <select
                className={inputCls}
                value={v.workflow ?? ""}
                onChange={e => {
                  const next = e.target.value;
                  // Clear args when swapping workflows — old inputs won't map.
                  onChange({ ...v, workflow: next, args: {} });
                }}
              >
                <option value="">— select workflow —</option>
                {workflows.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                className={inputCls}
                value={v.workflow ?? ""}
                placeholder="workflow-id (registry empty — type manually)"
                onChange={e => onChange({ ...v, workflow: e.target.value })}
              />
            )}
          </label>

          {selectedWorkflow?.description && (
            <p className="text-[10px] text-muted-foreground italic px-1">
              {selectedWorkflow.description}
            </p>
          )}

          {/* Payload / input mapping */}
          {selectedWorkflow && selectedWorkflow.inputs.length > 0 && (
            <div className="mt-2 pt-2 border-t space-y-1.5">
              <div className={labelTextCls}>
                Payload (workflow inputs)
              </div>
              <p className="text-[10px] text-muted-foreground">
                Enter a literal value or an expression like <code>{"{{row.id}}"}</code>,
                <code>{" {{route.id}}"}</code>, <code>{" {{auth.user.id}}"}</code>.
                Leave blank to omit.
              </p>
              {selectedWorkflow.inputs.map((inp) => (
                <div key={inp.name} className="flex items-baseline gap-2">
                  <span
                    className="text-[10px] font-mono text-foreground w-1/3 truncate"
                    title={inp.name}
                  >
                    {inp.name}
                    {inp.type && (
                      <span className="text-muted-foreground"> ({inp.type})</span>
                    )}
                  </span>
                  <input
                    type="text"
                    className={inputCls}
                    value={String(v.args?.[inp.name] ?? "")}
                    placeholder={`value or {{expression}}`}
                    onChange={e => setArg(inp.name, e.target.value)}
                  />
                </div>
              ))}
            </div>
          )}

          {selectedWorkflow && selectedWorkflow.inputs.length === 0 && (
            <p className="text-[10px] text-muted-foreground italic px-1">
              This workflow has no declared inputs.
            </p>
          )}
        </>
      )}

      {type === "submitForm" && (
        <label className={labelCls}>
          <span className={labelTextCls}>Target form id</span>
          <input
            type="text"
            className={inputCls}
            value={v.target ?? ""}
            placeholder="form node id"
            onChange={e => onChange({ ...v, target: e.target.value })}
          />
        </label>
      )}

      {type === "openModal" && (
        <label className={labelCls}>
          <span className={labelTextCls}>Modal id</span>
          <input
            type="text"
            className={inputCls}
            value={v.modal ?? ""}
            placeholder="modal id"
            onChange={e => onChange({ ...v, modal: e.target.value })}
          />
        </label>
      )}
    </div>
  );
}
