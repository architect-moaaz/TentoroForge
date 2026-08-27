"use client";

import { useMemo } from "react";
import {
  Plus,
  Minus,
  Edit3,
  ArrowLeftRight,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type {
  DecisionTableDefinition,
  DecisionTableRule,
} from "@/types/decision";

interface DecisionDiffViewProps {
  oldTable: DecisionTableDefinition;
  newTable: DecisionTableDefinition;
  oldLabel?: string;
  newLabel?: string;
}

type RowDiffType = "added" | "removed" | "changed" | "unchanged";

interface RuleDiff {
  type: RowDiffType;
  oldRule: DecisionTableRule | null;
  newRule: DecisionTableRule | null;
  changedCells: number[]; // indices of changed cells (input+output combined)
}

function rulesMatch(
  a: DecisionTableRule,
  b: DecisionTableRule,
): boolean {
  return (
    JSON.stringify(a.inputEntries) === JSON.stringify(b.inputEntries) &&
    JSON.stringify(a.outputEntries) === JSON.stringify(b.outputEntries) &&
    (a.annotation || "") === (b.annotation || "")
  );
}

function findChangedCells(
  a: DecisionTableRule,
  b: DecisionTableRule,
): number[] {
  const changed: number[] = [];
  const allOld = [...a.inputEntries, ...a.outputEntries];
  const allNew = [...b.inputEntries, ...b.outputEntries];
  const maxLen = Math.max(allOld.length, allNew.length);
  for (let i = 0; i < maxLen; i++) {
    if ((allOld[i] || "") !== (allNew[i] || "")) {
      changed.push(i);
    }
  }
  return changed;
}

function computeDiff(
  oldTable: DecisionTableDefinition,
  newTable: DecisionTableDefinition,
): RuleDiff[] {
  const diffs: RuleDiff[] = [];
  const oldRules = oldTable.rules;
  const newRules = newTable.rules;

  // Build index by rule ID
  const oldById = new Map(oldRules.map((r) => [r.id, r]));
  const newById = new Map(newRules.map((r) => [r.id, r]));

  // Track which new rules were matched
  const matchedNew = new Set<string>();

  // Process old rules
  for (const oldRule of oldRules) {
    const newRule = newById.get(oldRule.id);
    if (!newRule) {
      diffs.push({ type: "removed", oldRule, newRule: null, changedCells: [] });
    } else {
      matchedNew.add(newRule.id);
      if (rulesMatch(oldRule, newRule)) {
        diffs.push({ type: "unchanged", oldRule, newRule, changedCells: [] });
      } else {
        const changedCells = findChangedCells(oldRule, newRule);
        diffs.push({ type: "changed", oldRule, newRule, changedCells });
      }
    }
  }

  // Process new rules that weren't matched
  for (const newRule of newRules) {
    if (!matchedNew.has(newRule.id) && !oldById.has(newRule.id)) {
      diffs.push({ type: "added", oldRule: null, newRule, changedCells: [] });
    }
  }

  return diffs;
}

const ROW_COLORS: Record<RowDiffType, string> = {
  added: "bg-green-50 border-l-2 border-l-green-500",
  removed: "bg-red-50 border-l-2 border-l-red-500",
  changed: "bg-amber-50 border-l-2 border-l-amber-500",
  unchanged: "",
};

const CELL_HIGHLIGHT = "bg-amber-200/50 font-semibold";

export function DecisionDiffView({
  oldTable,
  newTable,
  oldLabel = "Previous",
  newLabel = "Current",
}: DecisionDiffViewProps) {
  const diffs = useMemo(() => computeDiff(oldTable, newTable), [oldTable, newTable]);

  // Use new table's column structure for the header
  const allInputs = newTable.inputs;
  const allOutputs = newTable.outputs;

  // Check for structural changes
  const inputsChanged =
    JSON.stringify(oldTable.inputs.map((i) => i.name)) !==
    JSON.stringify(newTable.inputs.map((i) => i.name));
  const outputsChanged =
    JSON.stringify(oldTable.outputs.map((o) => o.name)) !==
    JSON.stringify(newTable.outputs.map((o) => o.name));
  const hitPolicyChanged = oldTable.hitPolicy !== newTable.hitPolicy;

  const stats = useMemo(() => {
    const added = diffs.filter((d) => d.type === "added").length;
    const removed = diffs.filter((d) => d.type === "removed").length;
    const changed = diffs.filter((d) => d.type === "changed").length;
    const unchanged = diffs.filter((d) => d.type === "unchanged").length;
    return { added, removed, changed, unchanged };
  }, [diffs]);

  return (
    <div className="space-y-3">
      {/* Header with diff summary */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ArrowLeftRight className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Version Diff</span>
          <span className="text-xs text-muted-foreground">
            {oldLabel} vs {newLabel}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {stats.added > 0 && (
            <Badge variant="secondary" className="gap-1 bg-green-100 text-green-700 text-[10px]">
              <Plus className="h-2.5 w-2.5" />
              {stats.added} added
            </Badge>
          )}
          {stats.removed > 0 && (
            <Badge variant="secondary" className="gap-1 bg-red-100 text-red-700 text-[10px]">
              <Minus className="h-2.5 w-2.5" />
              {stats.removed} removed
            </Badge>
          )}
          {stats.changed > 0 && (
            <Badge variant="secondary" className="gap-1 bg-amber-100 text-amber-700 text-[10px]">
              <Edit3 className="h-2.5 w-2.5" />
              {stats.changed} changed
            </Badge>
          )}
        </div>
      </div>

      {/* Structural changes banner */}
      {(hitPolicyChanged || inputsChanged || outputsChanged) && (
        <div className="rounded border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700">
          <span className="font-medium">Structure changed:</span>{" "}
          {hitPolicyChanged && (
            <span>
              Hit policy: {oldTable.hitPolicy} &rarr; {newTable.hitPolicy}.{" "}
            </span>
          )}
          {inputsChanged && <span>Input columns modified. </span>}
          {outputsChanged && <span>Output columns modified. </span>}
        </div>
      )}

      {/* Diff table */}
      <div className="overflow-x-auto rounded border">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              <th className="border bg-muted/30 px-1 py-1.5 text-[10px] w-8">#</th>
              <th className="border bg-muted/30 px-1 py-1.5 text-[10px] w-12">Diff</th>
              {allInputs.map((input) => (
                <th
                  key={input.id}
                  className="border bg-blue-50 px-2 py-1.5 text-left text-[10px] font-semibold text-blue-700"
                >
                  {input.name}
                </th>
              ))}
              {allOutputs.map((output) => (
                <th
                  key={output.id}
                  className="border bg-green-50 px-2 py-1.5 text-left text-[10px] font-semibold text-green-700"
                >
                  {output.name}
                </th>
              ))}
              <th className="border bg-muted/30 px-2 py-1.5 text-[10px] text-left font-semibold text-muted-foreground">
                Note
              </th>
            </tr>
          </thead>
          <tbody>
            {diffs.map((diff, index) => {
              const rule = diff.newRule || diff.oldRule;
              if (!rule) return null;

              const entries = [...rule.inputEntries, ...rule.outputEntries];
              const totalInputs = allInputs.length;

              return (
                <tr key={rule.id} className={ROW_COLORS[diff.type]}>
                  <td className="border px-1 py-1 text-center text-[10px] text-muted-foreground">
                    {index + 1}
                  </td>
                  <td className="border px-1 py-1 text-center">
                    {diff.type === "added" && (
                      <Plus className="mx-auto h-3 w-3 text-green-600" />
                    )}
                    {diff.type === "removed" && (
                      <Minus className="mx-auto h-3 w-3 text-red-600" />
                    )}
                    {diff.type === "changed" && (
                      <Edit3 className="mx-auto h-3 w-3 text-amber-600" />
                    )}
                  </td>
                  {/* Render input cells */}
                  {allInputs.map((_, ci) => {
                    const value = rule.inputEntries[ci] || "";
                    const isChanged =
                      diff.type === "changed" && diff.changedCells.includes(ci);
                    return (
                      <td
                        key={ci}
                        className={`border px-2 py-1 font-mono ${isChanged ? CELL_HIGHLIGHT : ""}`}
                      >
                        {value || (
                          <span className="italic text-muted-foreground">-</span>
                        )}
                        {isChanged && diff.oldRule && (
                          <div className="mt-0.5 text-[9px] text-red-500 line-through">
                            {diff.oldRule.inputEntries[ci] || "-"}
                          </div>
                        )}
                      </td>
                    );
                  })}
                  {/* Render output cells */}
                  {allOutputs.map((_, ci) => {
                    const globalIdx = totalInputs + ci;
                    const value = rule.outputEntries[ci] || "";
                    const isChanged =
                      diff.type === "changed" &&
                      diff.changedCells.includes(globalIdx);
                    return (
                      <td
                        key={`out-${ci}`}
                        className={`border px-2 py-1 font-mono ${isChanged ? CELL_HIGHLIGHT : ""}`}
                      >
                        {value || "\u00A0"}
                        {isChanged && diff.oldRule && (
                          <div className="mt-0.5 text-[9px] text-red-500 line-through">
                            {diff.oldRule.outputEntries[ci] || "\u00A0"}
                          </div>
                        )}
                      </td>
                    );
                  })}
                  <td className="border px-2 py-1 text-muted-foreground">
                    {rule.annotation || ""}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
        <div className="flex items-center gap-1">
          <div className="h-2.5 w-2.5 rounded-sm border-l-2 border-l-green-500 bg-green-50" />
          Added
        </div>
        <div className="flex items-center gap-1">
          <div className="h-2.5 w-2.5 rounded-sm border-l-2 border-l-red-500 bg-red-50" />
          Removed
        </div>
        <div className="flex items-center gap-1">
          <div className="h-2.5 w-2.5 rounded-sm border-l-2 border-l-amber-500 bg-amber-50" />
          Changed
        </div>
        <div className="flex items-center gap-1">
          <div className="h-2.5 w-2.5 rounded-sm bg-amber-200/50" />
          Changed cell
        </div>
      </div>
    </div>
  );
}
