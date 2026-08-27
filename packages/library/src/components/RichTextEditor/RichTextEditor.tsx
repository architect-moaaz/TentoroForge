"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { RichTextEditorPropsType } from "./RichTextEditor.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface RichTextEditorProps extends RichTextEditorPropsType {
  style?: StyleSlotT;
  onChange?: (html: string) => void;
}

interface ToolbarButton {
  label: string;
  cmd: string;
}

const TOOLBAR_BUTTONS: ToolbarButton[] = [
  { label: "Bold", cmd: "bold" },
  { label: "Italic", cmd: "italic" },
  { label: "Bullet list", cmd: "insertUnorderedList" },
];

export function RichTextEditor({
  name = "richtext",
  label,
  value,
  placeholder,
  bind: _bind,
  className,
  style,
  onChange,
}: RichTextEditorProps) {
  const editorRef = React.useRef<HTMLDivElement>(null);

  // Set initial HTML on mount without causing caret jumps on re-renders
  React.useEffect(() => {
    if (editorRef.current && value !== undefined) {
      editorRef.current.innerHTML = value;
    }
    // Only run on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleToolbarClick(cmd: string) {
    document.execCommand(cmd);
    if (editorRef.current) {
      onChange?.(editorRef.current.innerHTML);
    }
  }

  function handleInput(e: React.FormEvent<HTMLDivElement>) {
    onChange?.((e.target as HTMLDivElement).innerHTML);
  }

  return (
    <div
      data-rich-text-editor=""
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
      className={className}
    >
      {label && (
        <label className="block text-sm font-medium text-foreground mb-1">
          {label}
        </label>
      )}
      {/* Toolbar */}
      <div className="flex gap-1 p-1 border border-border rounded-t-md bg-muted">
        {TOOLBAR_BUTTONS.map(({ label: btnLabel, cmd }) => (
          <button
            key={cmd}
            type="button"
            aria-label={btnLabel}
            onClick={() => handleToolbarClick(cmd)}
            className="px-2 py-1 text-sm rounded hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {btnLabel}
          </button>
        ))}
      </div>
      {/* Editable region */}
      <div
        ref={editorRef}
        role="textbox"
        aria-multiline="true"
        aria-label={label ?? name}
        contentEditable
        suppressContentEditableWarning
        onInput={handleInput}
        data-placeholder={placeholder}
        className="min-h-[6rem] p-2 border border-t-0 border-border rounded-b-md bg-background text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
    </div>
  );
}
