"use client";

import { useCallback, useRef, useEffect } from "react";
import { Textarea } from "@/components/ui/textarea";
import { validateExpression, type VariableSchema } from "@/lib/feel-lite";

interface ExpressionEditorProps {
  value: string;
  onChange: (value: string) => void;
  variables?: VariableSchema[];
  height?: number;
  placeholder?: string;
}

/**
 * FEEL-lite expression editor with syntax validation.
 * Uses a Textarea with real-time validation feedback.
 * (Monaco integration can be added later for autocomplete.)
 */
export function ExpressionEditor({
  value,
  onChange,
  variables,
  height = 80,
  placeholder = 'e.g. customer.age >= 18 and status in ["active","pending"]',
}: ExpressionEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const validation = value ? validateExpression(value, variables) : null;
  const hasErrors = validation ? !validation.valid : false;
  const warnings = validation?.issues.filter((i) => i.severity === "warning") ?? [];

  return (
    <div className="space-y-1">
      <Textarea
        ref={textareaRef}
        className={`font-mono text-xs resize-none ${
          hasErrors
            ? "border-red-400 focus-visible:ring-red-400"
            : warnings.length > 0
              ? "border-amber-400 focus-visible:ring-amber-400"
              : ""
        }`}
        style={{ minHeight: height }}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
      />
      {validation && validation.issues.length > 0 && (
        <div className="space-y-0.5">
          {validation.issues.slice(0, 3).map((issue, i) => (
            <p
              key={i}
              className={`text-[10px] ${
                issue.severity === "error"
                  ? "text-red-500"
                  : issue.severity === "warning"
                    ? "text-amber-500"
                    : "text-muted-foreground"
              }`}
            >
              {issue.message}
            </p>
          ))}
        </div>
      )}
      {variables && variables.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {variables.slice(0, 8).map((v) => (
            <button
              key={v.name}
              type="button"
              className="inline-flex items-center rounded bg-muted/50 px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              onClick={() => {
                const ta = textareaRef.current;
                if (ta) {
                  const start = ta.selectionStart;
                  const end = ta.selectionEnd;
                  const newValue =
                    value.slice(0, start) + v.name + value.slice(end);
                  onChange(newValue);
                  // Restore cursor position
                  setTimeout(() => {
                    ta.focus();
                    ta.setSelectionRange(
                      start + v.name.length,
                      start + v.name.length,
                    );
                  }, 0);
                } else {
                  onChange(value + v.name);
                }
              }}
              title={v.label || v.name}
            >
              {v.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
