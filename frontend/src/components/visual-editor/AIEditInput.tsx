"use client";

import { useState, useCallback, forwardRef } from "react";
import { Send, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useVisualEditorStore } from "@/stores/visual-editor";
import { getSuggestions } from "@/lib/ai-suggestion-utils";

interface AIEditInputProps {
  onSubmit: (instruction: string, file?: string, line?: number, contextElement?: string) => void;
  isEditing: boolean;
  progress: { status: string | null; logs: string[]; filesChanged: string[] };
  onAbort: () => void;
}

export const AIEditInput = forwardRef<HTMLInputElement, AIEditInputProps>(
  function AIEditInput({ onSubmit, isEditing, progress, onAbort }, ref) {
    const [instruction, setInstruction] = useState("");
    const selectedElement = useVisualEditorStore((s) => s.selectedElement);
    const selectedSectionId = useVisualEditorStore((s) => s.selectedSectionId);

    const handleSubmit = useCallback(
      (text?: string) => {
        const value = text ?? instruction;
        if (!value.trim() || isEditing) return;

        const contextElement = selectedElement
          ? `${selectedElement.tagName}${selectedElement.className ? "." + selectedElement.className.split(/\s+/).join(".") : ""}`
          : undefined;

        onSubmit(
          value.trim(),
          selectedElement?.source?.file,
          selectedElement?.source?.line,
          contextElement,
        );
        setInstruction("");
      },
      [instruction, isEditing, selectedElement, onSubmit],
    );

    const placeholder = selectedElement
      ? `Describe a change to this ${selectedElement.tagName.toLowerCase()}...`
      : "Describe a change...";

    const suggestions = getSuggestions(selectedElement, selectedSectionId);

    return (
      <div className="border-t bg-background">
        {/* Progress */}
        {isEditing && progress.status && (
          <div className="flex items-center gap-2 border-b bg-blue-50 px-3 py-1.5">
            <Loader2 className="h-3 w-3 animate-spin text-blue-600" />
            <span className="text-xs text-blue-700 truncate">
              {progress.status}
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="ml-auto h-5 w-5"
              onClick={onAbort}
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        )}

        {/* Suggestion chips */}
        {!isEditing && suggestions.length > 0 && (
          <div className="flex items-center gap-1.5 px-3 pt-2 pb-0.5 overflow-x-auto">
            {suggestions.map((suggestion) => (
              <button
                key={suggestion}
                className="shrink-0 rounded-full border px-2.5 py-0.5 text-[10px] text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                onClick={() => handleSubmit(suggestion)}
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}

        {/* Input */}
        <div className="flex items-center gap-2 px-3 py-2">
          {selectedElement?.source && (
            <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
              {selectedElement.source.file.split("/").pop()}:
              {selectedElement.source.line}
            </span>
          )}
          <Input
            ref={ref}
            className="h-8 text-sm flex-1"
            placeholder={placeholder}
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit();
              }
            }}
            disabled={isEditing}
          />
          <Button
            size="icon"
            className="h-8 w-8 shrink-0"
            onClick={() => handleSubmit()}
            disabled={!instruction.trim() || isEditing}
          >
            {isEditing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
      </div>
    );
  },
);
