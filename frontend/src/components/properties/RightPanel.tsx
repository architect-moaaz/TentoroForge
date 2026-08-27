"use client";
import * as React from "react";
import { ChevronRight, ChevronLeft, PanelRightClose } from "lucide-react";
import { PropertiesPanelInner } from "./PropertiesPanel";
import { StylePanel } from "./StylePanel";
import { BindingsPanel } from "./BindingsPanel";
import { TokenEditor } from "@/components/editor/TokenEditor";

type Tab = "props" | "style" | "bindings" | "tokens";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "props", label: "Props" },
  { id: "style", label: "Style" },
  { id: "bindings", label: "Bindings" },
  { id: "tokens", label: "Tokens" },
];

const TAB_BTN = "flex-1 text-[11px] uppercase tracking-wide py-1.5";

interface RightPanelProps {
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
}

export function RightPanel({ collapsed = false, onToggleCollapsed }: RightPanelProps) {
  const [tab, setTab] = React.useState<Tab>("style");

  if (collapsed) {
    return (
      <aside className="w-10 border-l bg-background flex flex-col h-full">
        <button
          onClick={onToggleCollapsed}
          className="h-10 w-10 grid place-items-center hover:bg-muted text-muted-foreground hover:text-foreground border-b"
          title="Expand properties panel"
          aria-label="Expand properties panel"
        >
          <ChevronLeft size={16} />
        </button>
        {/* Vertical tab labels — click to expand directly to that tab */}
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => {
              setTab(t.id);
              onToggleCollapsed?.();
            }}
            className="flex-1 hover:bg-muted text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
            title={`Expand and show ${t.label}`}
            style={{ writingMode: "vertical-rl", transform: "rotate(180deg)" }}
          >
            {t.label}
          </button>
        ))}
      </aside>
    );
  }

  return (
    <aside className="w-72 border-l bg-background flex flex-col h-full">
      <header className="flex border-b items-stretch">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`${TAB_BTN} ${
              tab === t.id
                ? "border-b-2 border-foreground -mb-px font-medium"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
        {onToggleCollapsed && (
          <button
            onClick={onToggleCollapsed}
            className="px-2 grid place-items-center text-muted-foreground hover:text-foreground hover:bg-muted border-l"
            title="Collapse properties panel"
            aria-label="Collapse properties panel"
          >
            <PanelRightClose size={14} />
          </button>
        )}
      </header>

      <div className="flex-1 overflow-y-auto">
        {tab === "props" && <PropertiesPanelInner />}
        {tab === "style" && <StylePanel />}
        {tab === "bindings" && <BindingsPanel />}
        {tab === "tokens" && <TokenEditor />}
      </div>
    </aside>
  );
}
