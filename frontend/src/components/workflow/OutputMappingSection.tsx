"use client";

/**
 * OutputMappingSection — the "Outputs" area of the Properties panel v2.
 *
 * Model: every declared output is always available downstream via
 * `<nodeId>.output.<field>`. This section lets the author OPT-IN to
 * promote a specific output to a named process variable, giving
 * downstream nodes a cleaner handle like `{{newUserId}}` instead of
 * `{{create_user.output.inserted.id}}`.
 *
 * Blank/absent processVar name = not promoted; the raw path still works.
 */

import { useState } from "react";
import { Sparkles, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ActionContract, OutputMapping } from "./actionContracts";

interface OutputMappingSectionProps {
  contract: ActionContract;
  nodeId: string;
  outputMappings: OutputMapping[];
  onChange: (mappings: OutputMapping[]) => void;
}

export function OutputMappingSection({
  contract,
  nodeId,
  outputMappings,
  onChange,
}: OutputMappingSectionProps) {
  if (contract.outputs.length === 0) return null;

  const upsert = (m: OutputMapping) => {
    const next = outputMappings.filter((x) => x.output !== m.output);
    if (m.processVar) next.push(m);
    onChange(next);
  };

  const remove = (output: string) => {
    onChange(outputMappings.filter((m) => m.output !== output));
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-[10px] font-semibold uppercase text-muted-foreground">
          Outputs
        </Label>
        <span className="text-[10px] text-muted-foreground">
          {contract.outputs.length} declared
        </span>
      </div>

      <p className="text-[10px] text-muted-foreground leading-snug">
        Every output is available downstream as{" "}
        <code className="text-[9.5px]">{`{{${nodeId}.output.<field>}}`}</code>.
        Promote one to a named process variable for a cleaner handle.
      </p>

      <div className="space-y-1.5">
        {contract.outputs.map((param) => {
          const existing = outputMappings.find((m) => m.output === param.name);
          return (
            <OutputRow
              key={param.name}
              nodeId={nodeId}
              output={param.name}
              type={param.type}
              label={param.label ?? param.name}
              processVar={existing?.processVar ?? ""}
              onChange={(name) => upsert({ output: param.name, processVar: name })}
              onClear={() => remove(param.name)}
            />
          );
        })}
      </div>
    </div>
  );
}

function OutputRow({
  nodeId,
  output,
  type,
  label,
  processVar,
  onChange,
  onClear,
}: {
  nodeId: string;
  output: string;
  type: string;
  label: string;
  processVar: string;
  onChange: (v: string) => void;
  onClear: () => void;
}) {
  const [editing, setEditing] = useState<boolean>(!!processVar);

  return (
    <div className="rounded border border-slate-100 p-2">
      <div className="flex items-center gap-1.5">
        <Sparkles className="h-3 w-3 shrink-0 text-amber-500" />
        <span className="flex-1 text-[11px]">
          <span className="font-mono text-slate-700">{label}</span>
          <span className="ml-1 text-[9px] uppercase text-muted-foreground">
            {type}
          </span>
        </span>
        {!editing && !processVar && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-1.5 text-[10px] text-muted-foreground"
            onClick={() => setEditing(true)}
          >
            Promote…
          </Button>
        )}
        {(editing || processVar) && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            title="Un-promote (still reachable by full path)"
            onClick={() => {
              setEditing(false);
              onClear();
            }}
          >
            <Undo2 className="h-3 w-3 text-muted-foreground" />
          </Button>
        )}
      </div>
      {(editing || processVar) && (
        <div className="mt-1.5 space-y-0.5">
          <Input
            className="h-7 text-[11px] font-mono"
            placeholder="processVarName"
            value={processVar}
            onChange={(e) => onChange(e.target.value)}
            autoFocus
          />
          <p className="text-[9.5px] text-muted-foreground">
            Downstream can reference this as{" "}
            <code className="text-[9px]">{`{{${processVar || "…"}}}`}</code>
            {" · "}raw path{" "}
            <code className="text-[9px]">{`{{${nodeId}.output.${output}}}`}</code>{" "}
            always works.
          </p>
        </div>
      )}
    </div>
  );
}
