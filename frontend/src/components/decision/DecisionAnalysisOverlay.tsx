"use client";

import { AlertTriangle, XCircle, Info } from "lucide-react";
import type {
  DecisionTableDefinition,
  DecisionAnalysisResult,
} from "@/types/decision";

interface DecisionAnalysisOverlayProps {
  table: DecisionTableDefinition;
  analysis: DecisionAnalysisResult;
}

export function DecisionAnalysisOverlay({
  table,
  analysis,
}: DecisionAnalysisOverlayProps) {
  const hasIssues =
    analysis.deadRows.length > 0 ||
    analysis.overlaps.ruleIdPairs.length > 0 ||
    analysis.typeErrors.length > 0 ||
    !analysis.completeness.complete;

  if (!hasIssues) return null;

  return (
    <div className="space-y-1.5 rounded border border-amber-200 bg-amber-50/50 p-2">
      <div className="flex items-center gap-1.5">
        <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
        <span className="text-xs font-semibold text-amber-700">
          Analysis Issues
        </span>
      </div>

      {/* Completeness */}
      {!analysis.completeness.complete && (
        <div className="flex items-start gap-1.5">
          <Info className="h-3 w-3 text-blue-500 mt-0.5 shrink-0" />
          <div className="text-[10px] text-blue-700">
            <span className="font-medium">Missing coverage:</span>
            {analysis.completeness.missingCombinations.slice(0, 3).map((msg, i) => (
              <span key={i} className="block">{msg}</span>
            ))}
          </div>
        </div>
      )}

      {/* Dead rows */}
      {analysis.deadRows.length > 0 && (
        <div className="flex items-start gap-1.5">
          <XCircle className="h-3 w-3 text-red-500 mt-0.5 shrink-0" />
          <div className="text-[10px] text-red-700">
            <span className="font-medium">
              Dead rows ({analysis.deadRows.length}):
            </span>{" "}
            {analysis.deadRows.map((id) => {
              const idx = table.rules.findIndex((r) => r.id === id);
              return `Rule ${idx + 1}`;
            }).join(", ")}
            <span className="block text-red-600">
              These rows will never match because earlier rules always take priority.
            </span>
          </div>
        </div>
      )}

      {/* Overlaps */}
      {analysis.overlaps.ruleIdPairs.length > 0 && (
        <div className="flex items-start gap-1.5">
          <AlertTriangle className="h-3 w-3 text-amber-500 mt-0.5 shrink-0" />
          <div className="text-[10px] text-amber-700">
            <span className="font-medium">
              Overlapping rules ({analysis.overlaps.ruleIdPairs.length} pairs):
            </span>{" "}
            {analysis.overlaps.ruleIdPairs.slice(0, 3).map(([a, b]) => {
              const idxA = table.rules.findIndex((r) => r.id === a) + 1;
              const idxB = table.rules.findIndex((r) => r.id === b) + 1;
              return `${idxA}-${idxB}`;
            }).join(", ")}
          </div>
        </div>
      )}

      {/* Type errors */}
      {analysis.typeErrors.length > 0 && (
        <div className="flex items-start gap-1.5">
          <XCircle className="h-3 w-3 text-red-500 mt-0.5 shrink-0" />
          <div className="text-[10px] text-red-700">
            <span className="font-medium">
              Expression errors ({analysis.typeErrors.length}):
            </span>
            {analysis.typeErrors.slice(0, 3).map((err, i) => {
              const ruleIdx = table.rules.findIndex((r) => r.id === err.ruleId) + 1;
              return (
                <span key={i} className="block">
                  Rule {ruleIdx}, col {err.columnIndex + 1}: {err.message}
                </span>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
