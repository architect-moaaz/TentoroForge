"use client";

import { useState, useRef, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { ExpressionAutocomplete } from "./ExpressionAutocomplete";
import type { AppModel } from "@/types/app-model";

interface DecisionCellEditorProps {
  value: string;
  onChange: (value: string) => void;
  columnType?: "input" | "output";
  columnName?: string;
  placeholder?: string;
  appModel?: AppModel | null;
}

export function DecisionCellEditor({
  value,
  onChange,
  columnType = "input",
  columnName,
  placeholder,
  appModel,
}: DecisionCellEditorProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setEditValue(value);
  }, [value]);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const commitEdit = () => {
    setEditing(false);
    if (editValue !== value) {
      onChange(editValue);
    }
  };

  if (!editing) {
    const displayValue = value || (columnType === "input" ? "-" : "");
    const isWildcard = !value.trim() || value.trim() === "-";

    return (
      <div
        className={`flex h-8 cursor-pointer items-center px-2 text-xs font-mono hover:bg-muted/50 ${
          isWildcard && columnType === "input" ? "text-muted-foreground italic" : ""
        }`}
        onClick={() => setEditing(true)}
        title={value || (columnType === "input" ? "Any (wildcard)" : "Click to edit")}
      >
        <span className="truncate">{displayValue || "\u00A0"}</span>
      </div>
    );
  }

  // Use autocomplete-enabled editor when appModel is available
  if (appModel) {
    return (
      <ExpressionAutocomplete
        ref={inputRef}
        value={editValue}
        onChange={setEditValue}
        onCommit={commitEdit}
        onCancel={() => {
          setEditValue(value);
          setEditing(false);
        }}
        appModel={appModel}
        placeholder={placeholder || (columnType === "input" ? "- (any)" : "")}
      />
    );
  }

  return (
    <Input
      ref={inputRef}
      className="h-8 rounded-none border-0 border-b-2 border-indigo-400 text-xs font-mono focus-visible:ring-0 focus-visible:ring-offset-0"
      value={editValue}
      onChange={(e) => setEditValue(e.target.value)}
      onBlur={commitEdit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commitEdit();
        if (e.key === "Escape") {
          setEditValue(value);
          setEditing(false);
        }
      }}
      placeholder={placeholder || (columnType === "input" ? "- (any)" : "")}
    />
  );
}
