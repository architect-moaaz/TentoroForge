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
  // Mirror of the contentEditable's HTML. A contentEditable region is invisible
  // to FormData by construction, so the value has to be kept in React state and
  // shipped through a hidden input — otherwise `name` submitted nothing.
  const [html, setHtml] = React.useState<string>(value ?? "");

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
      setHtml(editorRef.current.innerHTML);
      onChange?.(editorRef.current.innerHTML);
    }
  }

  function handleInput(e: React.FormEvent<HTMLDivElement>) {
    const next = (e.target as HTMLDivElement).innerHTML;
    setHtml(next);
    onChange?.(next);
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
      {/* Carry the HTML into the enclosing form's FormData under `name`. */}
      {name && <input type="hidden" name={name} value={html} readOnly />}
    </div>
  );
}
