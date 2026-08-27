"use client";

import { useCallback } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { HitPolicySelector } from "./HitPolicySelector";
import { DecisionColumnHeader } from "./DecisionColumnHeader";
import { DecisionRuleRow } from "./DecisionRuleRow";
import type {
  DecisionTableDefinition,
  DecisionTableInput,
  DecisionTableOutput,
  DecisionTableRule,
  HitPolicy,
  DecisionAnalysisResult,
} from "@/types/decision";
import type { AppModel } from "@/types/app-model";

interface DecisionTableEditorProps {
  table: DecisionTableDefinition;
  onChange: (table: DecisionTableDefinition) => void;
  compact?: boolean;
  readOnly?: boolean;
  analysis?: DecisionAnalysisResult | null;
  appModel?: AppModel | null;
}

let nextId = 1;
function genId(prefix: string) {
  return `${prefix}_${Date.now()}_${nextId++}`;
}

export function DecisionTableEditor({
  table,
  onChange,
  compact,
  readOnly,
  analysis,
  appModel,
}: DecisionTableEditorProps) {
  const updateHitPolicy = useCallback(
    (hitPolicy: HitPolicy) => onChange({ ...table, hitPolicy }),
    [table, onChange],
  );

  const addInputColumn = useCallback(() => {
    const newInput: DecisionTableInput = {
      id: genId("inp"),
      name: `input${table.inputs.length + 1}`,
      type: "string",
    };
    const rules = table.rules.map((r) => ({
      ...r,
      inputEntries: [...r.inputEntries, ""],
    }));
    onChange({ ...table, inputs: [...table.inputs, newInput], rules });
  }, [table, onChange]);

  const addOutputColumn = useCallback(() => {
    const newOutput: DecisionTableOutput = {
      id: genId("out"),
      name: `output${table.outputs.length + 1}`,
      type: "string",
    };
    const rules = table.rules.map((r) => ({
      ...r,
      outputEntries: [...r.outputEntries, ""],
    }));
    onChange({ ...table, outputs: [...table.outputs, newOutput], rules });
  }, [table, onChange]);

  const addRule = useCallback(() => {
    const newRule: DecisionTableRule = {
      id: genId("rule"),
      inputEntries: table.inputs.map(() => ""),
      outputEntries: table.outputs.map(() => ""),
    };
    onChange({ ...table, rules: [...table.rules, newRule] });
  }, [table, onChange]);

  const updateRule = useCallback(
    (index: number, rule: DecisionTableRule) => {
      const rules = [...table.rules];
      rules[index] = rule;
      onChange({ ...table, rules });
    },
    [table, onChange],
  );

  const deleteRule = useCallback(
    (index: number) => {
      onChange({ ...table, rules: table.rules.filter((_, i) => i !== index) });
    },
    [table, onChange],
  );

  const updateInput = useCallback(
    (index: number, updates: Partial<DecisionTableInput>) => {
      const inputs = [...table.inputs];
      inputs[index] = { ...inputs[index], ...updates };
      onChange({ ...table, inputs });
    },
    [table, onChange],
  );

  const updateOutput = useCallback(
    (index: number, updates: Partial<DecisionTableOutput>) => {
      const outputs = [...table.outputs];
      outputs[index] = { ...outputs[index], ...updates };
      onChange({ ...table, outputs });
    },
    [table, onChange],
  );

  const deleteInputColumn = useCallback(
    (index: number) => {
      const inputs = table.inputs.filter((_, i) => i !== index);
      const rules = table.rules.map((r) => ({
        ...r,
        inputEntries: r.inputEntries.filter((_, i) => i !== index),
      }));
      onChange({ ...table, inputs, rules });
    },
    [table, onChange],
  );

  const deleteOutputColumn = useCallback(
    (index: number) => {
      const outputs = table.outputs.filter((_, i) => i !== index);
      const rules = table.rules.map((r) => ({
        ...r,
        outputEntries: r.outputEntries.filter((_, i) => i !== index),
      }));
      onChange({ ...table, outputs, rules });
    },
    [table, onChange],
  );

  // Build highlight map from analysis
  const ruleHighlights = new Map<string, "dead" | "overlap">();
  if (analysis) {
    for (const id of analysis.deadRows) {
      ruleHighlights.set(id, "dead");
    }
    for (const [a, b] of analysis.overlaps.ruleIdPairs) {
      if (!ruleHighlights.has(a)) ruleHighlights.set(a, "overlap");
      if (!ruleHighlights.has(b)) ruleHighlights.set(b, "overlap");
    }
  }

  return (
    <div className="space-y-2">
      {/* Hit policy selector */}
      <div className="flex items-center gap-2">
        <Label className="text-xs shrink-0">Hit Policy</Label>
        <HitPolicySelector
          value={table.hitPolicy}
          onChange={updateHitPolicy}
          compact={compact}
        />
        <span className="text-[10px] text-muted-foreground">
          {table.rules.length} rule{table.rules.length !== 1 ? "s" : ""} ·{" "}
          {table.inputs.length} input{table.inputs.length !== 1 ? "s" : ""} ·{" "}
          {table.outputs.length} output{table.outputs.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Analysis banner */}
      {analysis && !analysis.completeness.complete && (
        <div className="rounded bg-amber-50 border border-amber-200 px-2 py-1 text-[10px] text-amber-700">
          Missing coverage: {analysis.completeness.missingCombinations.slice(0, 2).join("; ")}
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded border">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              <th className="border bg-muted/30 px-1 py-1.5 text-[10px] w-8">#</th>
              {table.inputs.map((input, i) => (
                <DecisionColumnHeader
                  key={input.id}
                  column={input}
                  columnType="input"
                  onRename={(name) => updateInput(i, { name })}
                  onChangeType={(type) => updateInput(i, { type })}
                  onDelete={() => deleteInputColumn(i)}
                  readOnly={readOnly}
                />
              ))}
              {table.outputs.map((output, i) => (
                <DecisionColumnHeader
                  key={output.id}
                  column={output}
                  columnType="output"
                  onRename={(name) => updateOutput(i, { name })}
                  onChangeType={(type) => updateOutput(i, { type })}
                  onDelete={() => deleteOutputColumn(i)}
                  readOnly={readOnly}
                />
              ))}
              <th className="border bg-muted/30 px-2 py-1.5 text-[10px] text-left font-semibold text-muted-foreground">
                Note
              </th>
              {!readOnly && <th className="w-6 bg-muted/30" />}
            </tr>
          </thead>
          <tbody>
            {table.rules.map((rule, i) => (
              <DecisionRuleRow
                key={rule.id}
                rule={rule}
                index={i}
                table={table}
                onChange={(r) => updateRule(i, r)}
                onDelete={() => deleteRule(i)}
                readOnly={readOnly}
                highlighted={ruleHighlights.get(rule.id) || null}
                appModel={appModel}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Add buttons */}
      {!readOnly && (
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="h-7 text-xs" onClick={addRule}>
            <Plus className="h-3 w-3 mr-1" />
            Rule
          </Button>
          <Button variant="outline" size="sm" className="h-7 text-xs" onClick={addInputColumn}>
            <Plus className="h-3 w-3 mr-1" />
            Input
          </Button>
          <Button variant="outline" size="sm" className="h-7 text-xs" onClick={addOutputColumn}>
            <Plus className="h-3 w-3 mr-1" />
            Output
          </Button>
        </div>
      )}
    </div>
  );
}
