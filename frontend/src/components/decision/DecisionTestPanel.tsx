"use client";

import { useState, useCallback } from "react";
import { Play, Plus, Trash2, CheckCircle, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { evaluateDecisionTable } from "@/lib/decision/table-evaluator";
import type {
  DecisionTableDefinition,
  DecisionTableResult,
  DecisionTestCase,
} from "@/types/decision";

interface DecisionTestPanelProps {
  table: DecisionTableDefinition;
  onClose?: () => void;
}

interface TestCaseState {
  id: string;
  name: string;
  inputs: Record<string, string>;
  expectedOutputs: Record<string, string>;
  result?: DecisionTableResult;
  passed?: boolean;
}

let nextId = 1;

export function DecisionTestPanel({ table, onClose }: DecisionTestPanelProps) {
  const [testCases, setTestCases] = useState<TestCaseState[]>([
    createEmptyTestCase(),
  ]);

  function createEmptyTestCase(): TestCaseState {
    const inputs: Record<string, string> = {};
    for (const inp of table.inputs) {
      inputs[inp.name] = "";
    }
    const expectedOutputs: Record<string, string> = {};
    for (const out of table.outputs) {
      expectedOutputs[out.name] = "";
    }
    return {
      id: `tc_${nextId++}`,
      name: `Test ${nextId - 1}`,
      inputs,
      expectedOutputs,
    };
  }

  const addTestCase = useCallback(() => {
    setTestCases((prev) => [...prev, createEmptyTestCase()]);
  }, [table]);

  const removeTestCase = useCallback((id: string) => {
    setTestCases((prev) => prev.filter((tc) => tc.id !== id));
  }, []);

  const updateTestCaseInput = useCallback(
    (id: string, field: string, value: string) => {
      setTestCases((prev) =>
        prev.map((tc) =>
          tc.id === id
            ? { ...tc, inputs: { ...tc.inputs, [field]: value } }
            : tc,
        ),
      );
    },
    [],
  );

  const updateTestCaseExpected = useCallback(
    (id: string, field: string, value: string) => {
      setTestCases((prev) =>
        prev.map((tc) =>
          tc.id === id
            ? {
                ...tc,
                expectedOutputs: { ...tc.expectedOutputs, [field]: value },
              }
            : tc,
        ),
      );
    },
    [],
  );

  const runSingleTest = useCallback(
    (id: string) => {
      setTestCases((prev) =>
        prev.map((tc) => {
          if (tc.id !== id) return tc;

          // Convert string inputs to typed values
          const typedInputs: Record<string, unknown> = {};
          for (const [key, val] of Object.entries(tc.inputs)) {
            typedInputs[key] = coerceInput(val);
          }

          try {
            const result = evaluateDecisionTable(table, typedInputs);
            const output = Array.isArray(result.result)
              ? result.result[0] ?? {}
              : result.result;

            // Check expected outputs
            let passed = true;
            for (const [key, expected] of Object.entries(tc.expectedOutputs)) {
              if (!expected) continue;
              const actual = String((output as Record<string, unknown>)[key] ?? "");
              if (actual !== expected) {
                passed = false;
                break;
              }
            }

            // If no expected values set, pass if any rule matched
            const hasExpected = Object.values(tc.expectedOutputs).some(
              (v) => v.trim() !== "",
            );
            if (!hasExpected) {
              passed = result.matchedRuleIds.length > 0;
            }

            return { ...tc, result, passed };
          } catch (e) {
            return { ...tc, passed: false };
          }
        }),
      );
    },
    [table],
  );

  const runAllTests = useCallback(() => {
    for (const tc of testCases) {
      runSingleTest(tc.id);
    }
  }, [testCases, runSingleTest]);

  const passedCount = testCases.filter((tc) => tc.passed === true).length;
  const failedCount = testCases.filter((tc) => tc.passed === false).length;
  const totalRun = testCases.filter((tc) => tc.passed !== undefined).length;

  return (
    <div className="space-y-3 rounded border bg-muted/10 p-3">
      <div className="flex items-center justify-between">
        <Label className="text-xs font-semibold">Test Cases</Label>
        <div className="flex items-center gap-2">
          {totalRun > 0 && (
            <span className="text-[10px] text-muted-foreground">
              {passedCount}/{totalRun} passed
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            className="h-6 text-[10px]"
            onClick={runAllTests}
          >
            <Play className="h-3 w-3 mr-1" />
            Run All
          </Button>
        </div>
      </div>

      {testCases.map((tc, idx) => (
        <div
          key={tc.id}
          className={`space-y-2 rounded border p-2 ${
            tc.passed === true
              ? "border-green-300 bg-green-50/50"
              : tc.passed === false
                ? "border-red-300 bg-red-50/50"
                : ""
          }`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              {tc.passed === true && (
                <CheckCircle className="h-3.5 w-3.5 text-green-500" />
              )}
              {tc.passed === false && (
                <XCircle className="h-3.5 w-3.5 text-red-500" />
              )}
              <span className="text-xs font-medium">{tc.name}</span>
            </div>
            <div className="flex gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5"
                onClick={() => runSingleTest(tc.id)}
                title="Run test"
              >
                <Play className="h-3 w-3" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5"
                onClick={() => removeTestCase(tc.id)}
                title="Remove test"
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          </div>

          {/* Inputs */}
          <div className="grid grid-cols-2 gap-1">
            {table.inputs.map((inp) => (
              <div key={inp.id}>
                <label className="text-[10px] text-muted-foreground">
                  {inp.name}
                </label>
                <Input
                  className="h-6 text-[10px] font-mono"
                  placeholder={inp.type}
                  value={tc.inputs[inp.name] || ""}
                  onChange={(e) =>
                    updateTestCaseInput(tc.id, inp.name, e.target.value)
                  }
                />
              </div>
            ))}
          </div>

          {/* Expected outputs */}
          <div className="grid grid-cols-2 gap-1">
            {table.outputs.map((out) => (
              <div key={out.id}>
                <label className="text-[10px] text-muted-foreground">
                  Expected: {out.name}
                </label>
                <Input
                  className="h-6 text-[10px] font-mono"
                  placeholder="(optional)"
                  value={tc.expectedOutputs[out.name] || ""}
                  onChange={(e) =>
                    updateTestCaseExpected(tc.id, out.name, e.target.value)
                  }
                />
              </div>
            ))}
          </div>

          {/* Result */}
          {tc.result && (
            <div className="rounded bg-muted/30 p-1.5 text-[10px] font-mono">
              <div className="text-muted-foreground">
                Matched: {tc.result.matchedRuleIds.length} rule(s)
              </div>
              {tc.result.matchedRuleIds.length > 0 && (
                <div>
                  Output:{" "}
                  {JSON.stringify(
                    Array.isArray(tc.result.result)
                      ? tc.result.result[0]
                      : tc.result.result,
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      ))}

      <Button
        variant="outline"
        size="sm"
        className="h-6 text-[10px] w-full"
        onClick={addTestCase}
      >
        <Plus className="h-3 w-3 mr-1" />
        Add Test Case
      </Button>
    </div>
  );
}

function coerceInput(value: string): unknown {
  if (!value.trim()) return undefined;
  if (value.toLowerCase() === "true") return true;
  if (value.toLowerCase() === "false") return false;
  if (value.toLowerCase() === "null") return null;
  const n = Number(value);
  if (!isNaN(n) && value.trim() !== "") return n;
  return value;
}
