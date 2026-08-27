"use client";

import { useMemo, useState } from "react";
import { Play, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { evaluateExpression } from "@/lib/feel-lite";
import { ACTION_META, type RuleAction } from "@/types/business-rules";

interface RulePlaygroundProps {
  /** Compiled FEEL-lite condition for the rule being edited. */
  whenFeel: string;
  then: RuleAction[];
  otherwise: RuleAction[];
  /** Field names of the model — used to seed a sample record. */
  fields: string[];
}

interface RunResult {
  ok: boolean;
  matched?: boolean;
  error?: string;
}

function describeAction(a: RuleAction): string {
  const meta = ACTION_META[a.type];
  const target = a.field ? ` → ${a.field}` : "";
  const val = a.value ? ` = ${a.value}` : "";
  const msg = a.message ? `: "${a.message}"` : "";
  return `${meta.label}${target}${val}${msg}`;
}

export function RulePlayground({ whenFeel, then: thenActions, otherwise, fields }: RulePlaygroundProps) {
  const seed = useMemo(() => {
    const obj: Record<string, unknown> = {};
    for (const f of fields) obj[f] = "";
    return JSON.stringify(obj, null, 2);
  }, [fields]);

  const [sample, setSample] = useState<string>(seed);
  const [result, setResult] = useState<RunResult | null>(null);

  const run = () => {
    let ctx: Record<string, unknown>;
    try {
      ctx = sample.trim() ? JSON.parse(sample) : {};
    } catch {
      setResult({ ok: false, error: "Sample record is not valid JSON." });
      return;
    }
    try {
      const raw = evaluateExpression(whenFeel || "true", ctx);
      setResult({ ok: true, matched: Boolean(raw) });
    } catch (e) {
      setResult({ ok: false, error: `Evaluation error: ${(e as Error).message}` });
    }
  };

  const firedActions = result?.matched ? thenActions : otherwise;

  return (
    <div className="space-y-3 rounded-md border bg-muted/10 p-3">
      <div className="flex items-center justify-between">
        <Label className="text-xs font-semibold">Playground — test this rule</Label>
        <Button type="button" size="sm" className="h-7 text-xs" onClick={run}>
          <Play className="mr-1 h-3 w-3" />
          Run
        </Button>
      </div>

      <div>
        <Label className="text-[11px] text-muted-foreground">Sample record (JSON)</Label>
        <Textarea
          className="mt-1 min-h-[120px] font-mono text-xs"
          value={sample}
          onChange={(e) => setSample(e.target.value)}
          spellCheck={false}
        />
      </div>

      <div className="rounded-md border bg-background p-2.5">
        <p className="mb-1 text-[11px] text-muted-foreground">Compiled condition (FEEL):</p>
        <code className="block whitespace-pre-wrap break-words text-[11px] text-indigo-700 dark:text-indigo-300">
          {whenFeel || "true"}
        </code>
      </div>

      {result && (
        <div className="space-y-2">
          {!result.ok ? (
            <div className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400">
              <AlertTriangle className="h-4 w-4" />
              {result.error}
            </div>
          ) : (
            <>
              <div
                className={`flex items-center gap-2 text-xs font-medium ${
                  result.matched
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-rose-600 dark:text-rose-400"
                }`}
              >
                {result.matched ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : (
                  <XCircle className="h-4 w-4" />
                )}
                Condition is {result.matched ? "TRUE" : "FALSE"} — running the{" "}
                {result.matched ? "Then" : "Else"} actions
              </div>
              <ul className="space-y-1 pl-1">
                {firedActions.length === 0 ? (
                  <li className="text-[11px] text-muted-foreground">(no actions on this branch)</li>
                ) : (
                  firedActions.map((a) => (
                    <li key={a.id} className="text-[11px] text-foreground">
                      • {describeAction(a)}
                    </li>
                  ))
                )}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
