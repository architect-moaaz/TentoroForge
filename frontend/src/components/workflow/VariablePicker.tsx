"use client";

import { useState, useMemo } from "react";
import { Variable } from "lucide-react";
import { Input } from "@/components/ui/input";
import type { AppModel } from "@/types/app-model";
import type {
  ProcessVariable,
  WorkflowNodeSerialized,
} from "@/types/workflow";
import { collectWorkflowVariables } from "./workflowVariables";

interface VariablePickerProps {
  appModel: AppModel | null;
  nodes: WorkflowNodeSerialized[];
  currentNodeId: string;
  processVariables?: ProcessVariable[];
  onInsert: (variable: string) => void;
}

/**
 * VariablePicker — legacy free-form inserter used by the description
 * field (and any other author-anywhere spot). Now backed by the shared
 * `collectWorkflowVariables` helper so it stays in sync with what
 * downstream contracts declare.
 *
 * Groups (in order):
 *   1. Process variables (named handles promoted from node outputs)
 *   2. Trigger fields
 *   3. Upstream node outputs (per declared contract)
 *   4. System fields
 */
export function VariablePicker({
  appModel,
  nodes,
  currentNodeId,
  processVariables,
  onInsert,
}: VariablePickerProps) {
  const [search, setSearch] = useState("");

  const variables = useMemo(
    () =>
      collectWorkflowVariables({
        processVariables,
        appModel,
        nodes,
        currentNodeId,
      }),
    [processVariables, appModel, nodes, currentNodeId],
  );

  const filtered = search
    ? variables.filter(
        (v) =>
          v.path.toLowerCase().includes(search.toLowerCase()) ||
          v.sourceLabel.toLowerCase().includes(search.toLowerCase()),
      )
    : variables;

  const grouped = useMemo(() => {
    const groups = new Map<string, typeof filtered>();
    for (const v of filtered) {
      const existing = groups.get(v.sourceLabel) || [];
      existing.push(v);
      groups.set(v.sourceLabel, existing);
    }
    return groups;
  }, [filtered]);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1">
        <Variable className="h-3 w-3 text-muted-foreground" />
        <span className="text-[10px] font-semibold uppercase text-muted-foreground">
          Variables
        </span>
      </div>
      <Input
        className="h-7 text-xs"
        placeholder="Search variables..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <div className="max-h-[240px] overflow-y-auto space-y-1">
        {Array.from(grouped).map(([source, vars]) => (
          <div key={source}>
            <div className="text-[10px] font-medium text-muted-foreground px-1 py-0.5">
              {source}
            </div>
            {vars.map((v) => (
              <button
                key={v.path}
                type="button"
                className="w-full rounded px-2 py-0.5 text-left text-[11px] font-mono text-slate-600 hover:bg-muted/50"
                onClick={() => onInsert(`{{${v.path}}}`)}
                title={v.type}
              >
                {v.path}
              </button>
            ))}
          </div>
        ))}
        {filtered.length === 0 && (
          <p className="text-center text-[10px] text-muted-foreground py-2">
            No variables found
          </p>
        )}
      </div>
    </div>
  );
}
