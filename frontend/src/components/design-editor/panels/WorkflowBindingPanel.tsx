"use client";

/**
 * Workflow Binding Panel — browse workflows and connect them
 * to form elements in the GrapeJS editor.
 */

import { useEffect, useState, useCallback } from "react";
import type { Editor, Component as GjsComponent } from "grapesjs";
import { Workflow, Play, Link2, Zap } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface WorkflowBindingPanelProps {
  editor: Editor | null;
  projectId: string;
}

interface WorkflowInfo {
  id: string;
  name: string;
  trigger?: { type: string };
  nodeCount: number;
}

export function WorkflowBindingPanel({ editor, projectId }: WorkflowBindingPanelProps) {
  const [workflows, setWorkflows] = useState<WorkflowInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<GjsComponent | null>(null);

  // Track selected element
  useEffect(() => {
    if (!editor) return;
    const onSelect = (c: GjsComponent) => setSelected(c);
    const onDeselect = () => setSelected(null);
    editor.on("component:selected", onSelect);
    editor.on("component:deselected", onDeselect);
    return () => {
      editor.off("component:selected", onSelect);
      editor.off("component:deselected", onDeselect);
    };
  }, [editor]);

  // Load workflows
  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}/workflows`);
        if (res.ok) {
          const data = await res.json();
          const list = (data.workflows || data || []).map((w: any) => ({
            id: w.id,
            name: w.name || w.definition?.name || "Untitled",
            trigger: w.definition?.trigger,
            nodeCount: w.definition?.nodes?.length || 0,
          }));
          setWorkflows(list);
        }
      } catch (err) {
        console.warn("Failed to load workflows:", err);
      }
      setLoading(false);
    }
    load();
  }, [projectId]);

  // Connect workflow to selected form/button
  const connectWorkflow = useCallback(
    (workflowId: string, workflowName: string) => {
      if (!selected) return;

      selected.addAttributes({
        "data-action": "trigger-workflow",
        "data-action-workflow": workflowId,
      });

      // Show confirmation
      alert(`Connected "${workflowName}" to the selected element.\n\nThe form will trigger this workflow on submission.`);
    },
    [selected],
  );

  // Get current binding of selected element
  const currentWorkflow = selected?.getAttributes()?.["data-action-workflow"];

  if (loading) {
    return <div className="p-4 text-sm text-muted-foreground">Loading workflows...</div>;
  }

  return (
    <div className="p-4 space-y-4">
      <h3 className="text-sm font-semibold flex items-center gap-1.5">
        <Workflow className="h-4 w-4" /> Workflows
      </h3>

      {selected && (
        <div className="text-xs bg-muted/50 rounded-md p-2">
          <span className="font-medium">Selected:</span>{" "}
          {selected.get("tagName")}
          {currentWorkflow && (
            <span className="text-primary ml-1">→ {currentWorkflow}</span>
          )}
        </div>
      )}

      {workflows.length > 0 ? (
        <div className="space-y-2">
          {workflows.map((wf) => (
            <div
              key={wf.id}
              className="border rounded-md p-3 hover:bg-muted/50 transition-colors"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium">{wf.name}</span>
                {selected && (
                  <button
                    onClick={() => connectWorkflow(wf.id, wf.name)}
                    className="flex items-center gap-1 text-xs text-primary hover:underline"
                  >
                    <Link2 className="h-3 w-3" /> Connect
                  </button>
                )}
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                {wf.trigger && (
                  <span className="flex items-center gap-1">
                    <Zap className="h-3 w-3" />
                    {wf.trigger.type}
                  </span>
                )}
                <span>{wf.nodeCount} nodes</span>
                {currentWorkflow === wf.id && (
                  <span className="text-primary font-medium">● Connected</span>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-6">
          <Workflow className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">No workflows defined yet</p>
          <p className="text-xs text-muted-foreground mt-1">
            Create workflows in the Workflows tab first
          </p>
        </div>
      )}

      {!selected && workflows.length > 0 && (
        <p className="text-xs text-muted-foreground italic">
          Select a form or button to connect a workflow
        </p>
      )}
    </div>
  );
}
