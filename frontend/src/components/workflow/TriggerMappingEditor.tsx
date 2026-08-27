"use client";

/**
 * TriggerMappingEditor — maps trigger payload fields to values that
 * seed process variables at run-start.
 *
 * Rendered as the shared KeyValueMapper so the value dropdown has the
 * same reach as anywhere else in the panel (named process vars, trigger
 * fields, upstream node outputs, system fields) instead of only the
 * process-variables list.
 *
 * On disk the mapping is stored as a flat `Record<string, string>` where
 * each value may be a `{{path}}` reference or a literal. The runtime
 * walks nested references at exec time.
 */

import { Label } from "@/components/ui/label";
import { KeyValueMapper } from "./KeyValueMapper";
import type { ProcessVariable } from "@/types/workflow";
import type { WorkflowVariable } from "./workflowVariables";

interface TriggerMappingEditorProps {
  mapping: Record<string, string>;
  processVariables: ProcessVariable[];
  /** Full variable pool for the value dropdown. */
  variables?: WorkflowVariable[];
  onChange: (mapping: Record<string, string>) => void;
}

export function TriggerMappingEditor({
  mapping,
  processVariables,
  variables,
  onChange,
}: TriggerMappingEditorProps) {
  // If the caller didn't pass the fuller variable set, at least
  // surface named process variables so the dropdown isn't empty.
  const vars: WorkflowVariable[] =
    variables && variables.length > 0
      ? variables
      : processVariables.map((pv) => ({
          path: pv.name,
          type: pv.type,
          group: "process-variable" as const,
          sourceLabel: "Process variables",
        }));

  return (
    <div className="space-y-2">
      <Label className="text-[10px] font-semibold uppercase text-muted-foreground">
        Trigger input mapping
      </Label>
      <p className="text-[10px] text-muted-foreground leading-snug">
        Map payload fields (the key) to variable values (the value).
        Leave empty to copy the whole payload verbatim.
      </p>
      <KeyValueMapper
        value={mapping as Record<string, unknown>}
        variables={vars}
        onChange={(next) => {
          // Coerce every value to a string for the on-disk record.
          const flat: Record<string, string> = {};
          for (const [k, v] of Object.entries(next)) flat[k] = String(v ?? "");
          onChange(flat);
        }}
        keyPlaceholder="payload.field"
        addLabel="Add mapping"
      />
    </div>
  );
}
