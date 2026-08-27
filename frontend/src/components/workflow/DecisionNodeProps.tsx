"use client";

import { useState, useCallback } from "react";
import { Plus, TestTube } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { DecisionTableEditor } from "@/components/decision/DecisionTableEditor";
import { DecisionTestPanel } from "@/components/decision/DecisionTestPanel";
import type { WorkflowNodeConfig } from "@/types/workflow";
import type { DecisionTableDefinition } from "@/types/decision";

interface DecisionNodePropsComponentProps {
  config: WorkflowNodeConfig;
  onUpdate: (config: Partial<WorkflowNodeConfig>) => void;
}

function createEmptyTable(): DecisionTableDefinition {
  return {
    id: `dt_${Date.now()}`,
    name: "Decision Table",
    hitPolicy: "F",
    inputs: [
      { id: "inp_1", name: "input1", type: "string" },
    ],
    outputs: [
      { id: "out_1", name: "result", type: "string" },
    ],
    rules: [
      { id: "rule_1", inputEntries: [""], outputEntries: [""] },
    ],
  };
}

export function DecisionNodeProps({
  config,
  onUpdate,
}: DecisionNodePropsComponentProps) {
  const [showTest, setShowTest] = useState(false);

  const table: DecisionTableDefinition =
    config.decisionTable || createEmptyTable();

  const updateTable = useCallback(
    (updated: DecisionTableDefinition) => {
      onUpdate({ decisionTable: updated });
    },
    [onUpdate],
  );

  const outputMapping = config.outputMapping || {};

  const updateOutputMapping = useCallback(
    (column: string, variable: string) => {
      onUpdate({
        outputMapping: { ...outputMapping, [column]: variable },
      });
    },
    [onUpdate, outputMapping],
  );

  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs">Decision Table</Label>
        <p className="text-[10px] text-muted-foreground mb-2">
          Define rules as a spreadsheet. Each row is a rule. Input columns are
          conditions, output columns are results.
        </p>
      </div>

      {/* Initialize table if needed */}
      {!config.decisionTable && (
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs w-full"
          onClick={() => onUpdate({ decisionTable: createEmptyTable() })}
        >
          <Plus className="h-3 w-3 mr-1" />
          Create Decision Table
        </Button>
      )}

      {config.decisionTable && (
        <>
          <DecisionTableEditor
            table={table}
            onChange={updateTable}
            compact
          />

          <Separator />

          {/* Output mapping */}
          <div>
            <Label className="text-xs">Output Mapping</Label>
            <p className="text-[10px] text-muted-foreground mb-1">
              Map decision output columns to workflow variables
            </p>
            <div className="space-y-1">
              {table.outputs.map((output) => (
                <div key={output.id} className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground w-20 truncate">
                    {output.name}
                  </span>
                  <span className="text-[10px] text-muted-foreground">&rarr;</span>
                  <Input
                    className="h-7 text-xs flex-1 font-mono"
                    placeholder={output.name}
                    value={outputMapping[output.name] || ""}
                    onChange={(e) =>
                      updateOutputMapping(output.name, e.target.value)
                    }
                  />
                </div>
              ))}
            </div>
          </div>

          <Separator />

          {/* Test button */}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs w-full"
            onClick={() => setShowTest(!showTest)}
          >
            <TestTube className="h-3 w-3 mr-1" />
            {showTest ? "Hide Test Panel" : "Test Decision Table"}
          </Button>

          {showTest && (
            <DecisionTestPanel
              table={table}
              onClose={() => setShowTest(false)}
            />
          )}
        </>
      )}

      <p className="text-[10px] text-muted-foreground">
        Match exits right handle. No-match exits bottom handle.
      </p>
    </div>
  );
}
