"use client";

import {
  useState,
  useRef,
  useEffect,
  useMemo,
  useCallback,
  forwardRef,
  useImperativeHandle,
} from "react";
import { Input } from "@/components/ui/input";
import type { AppModel, TableModel, ColumnModel } from "@/types/app-model";

interface ExpressionAutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  onCommit: () => void;
  onCancel: () => void;
  appModel: AppModel | null | undefined;
  placeholder?: string;
  className?: string;
}

interface Suggestion {
  label: string;
  detail: string;
  insertText: string;
  type: "entity" | "field" | "operator" | "function" | "value";
}

const OPERATORS: Suggestion[] = [
  { label: "==", detail: "equals", insertText: "== ", type: "operator" },
  { label: "!=", detail: "not equals", insertText: "!= ", type: "operator" },
  { label: ">", detail: "greater than", insertText: "> ", type: "operator" },
  { label: ">=", detail: "greater or equal", insertText: ">= ", type: "operator" },
  { label: "<", detail: "less than", insertText: "< ", type: "operator" },
  { label: "<=", detail: "less or equal", insertText: "<= ", type: "operator" },
  { label: "in", detail: "contained in list", insertText: "in [", type: "operator" },
  { label: "not in", detail: "not in list", insertText: "not in [", type: "operator" },
  { label: "null", detail: "null value", insertText: "null", type: "value" },
  { label: "true", detail: "boolean true", insertText: "true", type: "value" },
  { label: "false", detail: "boolean false", insertText: "false", type: "value" },
];

const FUNCTIONS: Suggestion[] = [
  { label: "sum()", detail: "sum of values", insertText: "sum(", type: "function" },
  { label: "count()", detail: "count of items", insertText: "count(", type: "function" },
  { label: "min()", detail: "minimum value", insertText: "min(", type: "function" },
  { label: "max()", detail: "maximum value", insertText: "max(", type: "function" },
  { label: "avg()", detail: "average value", insertText: "avg(", type: "function" },
  { label: "length()", detail: "string length", insertText: "length(", type: "function" },
  { label: "contains()", detail: "string contains", insertText: 'contains(, "")', type: "function" },
  { label: "startsWith()", detail: "starts with", insertText: 'startsWith(, "")', type: "function" },
  { label: "now()", detail: "current timestamp", insertText: "now()", type: "function" },
  { label: "today()", detail: "current date", insertText: "today()", type: "function" },
];

function buildSchemaSuggestions(appModel: AppModel | null | undefined): Suggestion[] {
  if (!appModel?.database?.tables) return [];

  const suggestions: Suggestion[] = [];

  for (const table of appModel.database.tables) {
    // Entity name
    suggestions.push({
      label: table.name,
      detail: `entity (${table.columns.length} fields)`,
      insertText: table.name,
      type: "entity",
    });

    // Field names as entity.field
    for (const col of table.columns) {
      suggestions.push({
        label: `${table.name}.${col.name}`,
        detail: `${col.type}${col.nullable ? " (nullable)" : ""}`,
        insertText: `${table.name}.${col.name}`,
        type: "field",
      });

      // Also add standalone field name for when context is obvious
      suggestions.push({
        label: col.name,
        detail: `${table.name}.${col.name} (${col.type})`,
        insertText: col.name,
        type: "field",
      });
    }
  }

  return suggestions;
}

function getLastWord(text: string): string {
  // Get the last token being typed (after space, comma, paren, etc.)
  const match = text.match(/[\w.]+$/);
  return match ? match[0] : "";
}

const TYPE_COLORS: Record<string, string> = {
  entity: "text-blue-600",
  field: "text-purple-600",
  operator: "text-orange-600",
  function: "text-green-600",
  value: "text-rose-600",
};

export const ExpressionAutocomplete = forwardRef<
  HTMLInputElement,
  ExpressionAutocompleteProps
>(function ExpressionAutocomplete(
  {
    value,
    onChange,
    onCommit,
    onCancel,
    appModel,
    placeholder,
    className,
  },
  ref,
) {
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useImperativeHandle(ref, () => inputRef.current!);

  const schemaSuggestions = useMemo(
    () => buildSchemaSuggestions(appModel),
    [appModel],
  );

  const allSuggestions = useMemo(
    () => [...schemaSuggestions, ...OPERATORS, ...FUNCTIONS],
    [schemaSuggestions],
  );

  const lastWord = getLastWord(value);

  const filtered = useMemo(() => {
    if (!lastWord) return [];
    const q = lastWord.toLowerCase();
    return allSuggestions
      .filter(
        (s) =>
          s.label.toLowerCase().includes(q) ||
          s.detail.toLowerCase().includes(q),
      )
      .slice(0, 8);
  }, [allSuggestions, lastWord]);

  // Show suggestions only when typing and there are matches
  useEffect(() => {
    setShowSuggestions(filtered.length > 0 && lastWord.length > 0);
    setSelectedIndex(0);
  }, [filtered.length, lastWord]);

  // Scroll selected into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-index="${selectedIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  const applySuggestion = useCallback(
    (suggestion: Suggestion) => {
      // Replace the last word with the suggestion
      const beforeLastWord = value.slice(0, value.length - lastWord.length);
      const newValue = beforeLastWord + suggestion.insertText;
      onChange(newValue);
      setShowSuggestions(false);
      inputRef.current?.focus();
    },
    [value, lastWord, onChange],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (showSuggestions && filtered.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setSelectedIndex((i) => Math.max(i - 1, 0));
          return;
        }
        if (e.key === "Tab" || (e.key === "Enter" && filtered[selectedIndex])) {
          e.preventDefault();
          applySuggestion(filtered[selectedIndex]);
          return;
        }
      }

      if (e.key === "Enter") {
        onCommit();
      }
      if (e.key === "Escape") {
        if (showSuggestions) {
          setShowSuggestions(false);
        } else {
          onCancel();
        }
      }
    },
    [showSuggestions, filtered, selectedIndex, applySuggestion, onCommit, onCancel],
  );

  return (
    <div className="relative">
      <Input
        ref={inputRef}
        className={
          className ||
          "h-8 rounded-none border-0 border-b-2 border-indigo-400 text-xs font-mono focus-visible:ring-0 focus-visible:ring-offset-0"
        }
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => {
          // Delay hiding so click on suggestion works
          setTimeout(() => setShowSuggestions(false), 200);
        }}
        placeholder={placeholder}
        autoFocus
      />

      {/* Autocomplete dropdown */}
      {showSuggestions && filtered.length > 0 && (
        <div
          ref={listRef}
          className="absolute left-0 top-full z-50 mt-0.5 max-h-48 w-64 overflow-y-auto rounded-md border bg-popover shadow-md"
        >
          {filtered.map((suggestion, i) => (
            <button
              key={`${suggestion.label}-${i}`}
              data-index={i}
              className={`flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs ${
                i === selectedIndex
                  ? "bg-accent text-accent-foreground"
                  : "hover:bg-accent/50"
              }`}
              onMouseDown={(e) => {
                e.preventDefault();
                applySuggestion(suggestion);
              }}
              onMouseEnter={() => setSelectedIndex(i)}
            >
              <span
                className={`shrink-0 font-mono font-medium ${TYPE_COLORS[suggestion.type] || ""}`}
              >
                {suggestion.label}
              </span>
              <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">
                {suggestion.detail}
              </span>
            </button>
          ))}
          <div className="border-t px-2 py-1 text-[9px] text-muted-foreground">
            Tab to accept, Esc to close
          </div>
        </div>
      )}
    </div>
  );
});
