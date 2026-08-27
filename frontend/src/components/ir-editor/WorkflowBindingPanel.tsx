"use client";

/**
 * WorkflowBindingPanel — connects a Form node to a workflow.
 *
 * Shown in the "Workflows" tab of the IR editor Properties panel.
 * Lets the user pick a workflow and map form fields to workflow inputs.
 */

import { useEffect, useState, useCallback } from "react";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Loader2, Workflow, Link2Off, ArrowRight } from "lucide-react";
import { useIREditorStore, type IRNode, type NodePath } from "@/stores/ir-editor";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface WorkflowSchema {
  id: string;
  name: string;
  description: string;
  trigger: string;
  inputs: Array<{ name: string; type?: string }>;
}

function useRegistryWorkflows(projectId: string | null) {
  const [workflows, setWorkflows] = useState<WorkflowSchema[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    fetch(`${API_BASE}/api/projects/${projectId}/registry/workflows`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setWorkflows(Array.isArray(data) ? data : []))
      .catch(() => setWorkflows([]))
      .finally(() => setLoading(false));
  }, [projectId]);

  return { workflows, loading };
}

/** Collect all field names from a Form node (top-level fields + section fields). */
function collectFormFields(node: IRNode): string[] {
  const fields = new Set<string>();
  const topFields = node.fields as Array<{ field: string }> | undefined;
  topFields?.forEach((f) => f.field && fields.add(f.field));

  const sections = node.sections as Array<{ fields: Array<{ field: string }> }> | undefined;
  sections?.forEach((s) => s.fields?.forEach((f) => f.field && fields.add(f.field)));

  return Array.from(fields);
}

interface WorkflowBindingPanelProps {
  node: IRNode;
  selectedPath: NodePath;
}

export function WorkflowBindingPanel({ node, selectedPath }: WorkflowBindingPanelProps) {
  const projectId = useIREditorStore((s) => s.projectId);
  const applyOps = useIREditorStore((s) => s.applyOps);
  const { workflows, loading } = useRegistryWorkflows(projectId);

  const binding = node.onSuccessWorkflow as { workflowId: string; inputMapping: Record<string, string> } | undefined;
  const selectedWorkflow = workflows.find((w) => w.id === binding?.workflowId);
  const formFields = collectFormFields(node);

  const setBinding = useCallback(
    (patch: { workflowId?: string; inputMapping?: Record<string, string> } | null) => {
      applyOps([{
        type: "setProp",
        path: selectedPath,
        prop: "onSuccessWorkflow",
        value: patch === null ? undefined : { ...(binding || { workflowId: "", inputMapping: {} }), ...patch },
      }]);
    },
    [applyOps, selectedPath, binding],
  );

  if (node.node !== "Form") {
    return (
      <div className="p-3 text-xs text-muted-foreground">
        <p>Workflow binding is only available on Form nodes.</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-6">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (workflows.length === 0) {
    return (
      <div className="p-3 text-xs text-muted-foreground space-y-1">
        <p className="font-medium">No workflows found</p>
        <p>Define workflows in the project to connect them to this form.</p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-primary">
        <Workflow className="h-3.5 w-3.5" />
        Trigger Workflow on Submit
      </div>

      {/* Workflow picker */}
      <div className="space-y-1">
        <Label className="text-xs text-muted-foreground">Workflow</Label>
        <Select
          value={binding?.workflowId || "__none__"}
          onValueChange={(v) => {
            if (v === "__none__") {
              setBinding(null);
            } else {
              setBinding({ workflowId: v, inputMapping: {} });
            }
          }}
        >
          <SelectTrigger className="h-7 text-xs">
            <SelectValue placeholder="— None —" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">— None —</SelectItem>
            {workflows.map((wf) => (
              <SelectItem key={wf.id} value={wf.id}>
                {wf.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Workflow description */}
      {selectedWorkflow?.description && (
        <p className="text-[10px] text-muted-foreground italic">{selectedWorkflow.description}</p>
      )}

      {/* Input mapping */}
      {binding?.workflowId && selectedWorkflow && (
        <div className="space-y-2 pt-1 border-t">
          <p className="text-[10px] text-muted-foreground font-medium uppercase tracking-wide">
            Input mapping (form field → workflow input)
          </p>

          {selectedWorkflow.inputs.length === 0 && (
            <p className="text-[10px] text-muted-foreground">This workflow has no declared inputs.</p>
          )}

          {selectedWorkflow.inputs.map((input) => (
            <div key={input.name} className="flex items-center gap-1.5">
              <Select
                value={binding.inputMapping?.[input.name] || "__none__"}
                onValueChange={(fieldName) => {
                  const next = { ...(binding.inputMapping || {}) };
                  if (fieldName === "__none__") {
                    delete next[input.name];
                  } else {
                    next[input.name] = fieldName;
                  }
                  setBinding({ inputMapping: next });
                }}
              >
                <SelectTrigger className="h-6 text-[10px] flex-1">
                  <SelectValue placeholder="form field" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">— none —</SelectItem>
                  {formFields.map((f) => (
                    <SelectItem key={f} value={f}>{f}</SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <ArrowRight className="h-3 w-3 text-muted-foreground shrink-0" />

              <span className="text-[10px] font-mono text-foreground min-w-[60px] truncate" title={input.name}>
                {input.name}
              </span>
              {input.type && (
                <span className="text-[10px] text-muted-foreground">({input.type})</span>
              )}
            </div>
          ))}

          {/* Free-form mapping for workflows without declared inputs */}
          {selectedWorkflow.inputs.length === 0 && formFields.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] text-muted-foreground">Map form fields manually:</p>
              {formFields.map((fieldName) => (
                <div key={fieldName} className="flex items-center gap-1.5">
                  <span className="text-[10px] font-mono text-foreground flex-1">{fieldName}</span>
                  <ArrowRight className="h-3 w-3 text-muted-foreground shrink-0" />
                  <Input
                    value={binding.inputMapping?.[fieldName] || ""}
                    onChange={(e) => {
                      const next = { ...(binding.inputMapping || {}) };
                      if (e.target.value) {
                        next[fieldName] = e.target.value;
                      } else {
                        delete next[fieldName];
                      }
                      setBinding({ inputMapping: next });
                    }}
                    className="h-6 text-[10px] flex-1"
                    placeholder="workflow input key"
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {binding?.workflowId && (
        <Button
          variant="ghost"
          size="sm"
          className="h-6 text-xs text-muted-foreground w-full"
          onClick={() => setBinding(null)}
        >
          <Link2Off className="h-3 w-3 mr-1" />
          Disconnect workflow
        </Button>
      )}
    </div>
  );
}
