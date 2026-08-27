"use client";

import { useEffect, useRef } from "react";
import { Type, Paintbrush, Sparkles, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVisualEditorStore } from "@/stores/visual-editor";
import { QuickStylePopover } from "./QuickStylePopover";

interface ElementActionPopoverProps {
  onEditText: () => void;
  onAskAI: () => void;
  onDeleteElement: () => void;
  onStyleChange: (
    action: "add" | "remove" | "replace",
    cls: string,
    replaceCls?: string,
  ) => void;
}

export function ElementActionPopover({
  onEditText,
  onAskAI,
  onDeleteElement,
  onStyleChange,
}: ElementActionPopoverProps) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const show = useVisualEditorStore((s) => s.showActionPopover);
  const position = useVisualEditorStore((s) => s.actionPopoverPosition);
  const quickStyleTarget = useVisualEditorStore((s) => s.quickStyleTarget);
  const setShowActionPopover = useVisualEditorStore((s) => s.setShowActionPopover);
  const setQuickStyleTarget = useVisualEditorStore((s) => s.setQuickStyleTarget);

  // Dismiss on Escape
  useEffect(() => {
    if (!show) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setShowActionPopover(false);
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [show, setShowActionPopover]);

  if (!show || !position) return null;

  return (
    <div
      ref={popoverRef}
      className="absolute z-50 animate-in fade-in-0 zoom-in-95 duration-100"
      style={{ top: position.top, left: position.left }}
    >
      {quickStyleTarget ? (
        <QuickStylePopover
          onBack={() => setQuickStyleTarget(null)}
          onStyleChange={onStyleChange}
        />
      ) : (
        <div className="flex flex-col gap-0.5 rounded-lg border bg-popover p-1 shadow-lg min-w-[160px]">
          <Button
            variant="ghost"
            size="sm"
            className="justify-start gap-2 h-8 px-2 text-xs"
            onClick={onEditText}
          >
            <Type className="h-3.5 w-3.5" />
            Edit text
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="justify-start gap-2 h-8 px-2 text-xs"
            onClick={() => setQuickStyleTarget("bg")}
          >
            <Paintbrush className="h-3.5 w-3.5" />
            Quick style
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="justify-start gap-2 h-8 px-2 text-xs"
            onClick={onAskAI}
          >
            <Sparkles className="h-3.5 w-3.5" />
            Ask AI
          </Button>
          <div className="border-t my-0.5" />
          <Button
            variant="ghost"
            size="sm"
            className="justify-start gap-2 h-8 px-2 text-xs text-destructive hover:text-destructive"
            onClick={onDeleteElement}
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete element
          </Button>
        </div>
      )}
    </div>
  );
}
