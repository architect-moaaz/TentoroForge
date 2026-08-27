"use client";
import { useState } from "react";
import { PropertiesPanelInner } from "@/components/properties/PropertiesPanel";
import { TokenEditor } from "@/components/editor/TokenEditor";

type Tab = "props" | "tokens";

export function PropsTokensSidebar() {
  const [tab, setTab] = useState<Tab>("props");
  return (
    <aside className="w-72 border-l bg-muted/20 flex flex-col h-full">
      <header className="flex border-b">
        <button
          onClick={() => setTab("props")}
          className={`flex-1 text-xs uppercase tracking-wide py-2 ${
            tab === "props"
              ? "bg-background border-b-2 border-primary"
              : "text-muted-foreground hover:bg-background"
          }`}
        >
          Props
        </button>
        <button
          onClick={() => setTab("tokens")}
          className={`flex-1 text-xs uppercase tracking-wide py-2 ${
            tab === "tokens"
              ? "bg-background border-b-2 border-primary"
              : "text-muted-foreground hover:bg-background"
          }`}
        >
          Tokens
        </button>
      </header>
      <div className="flex-1 overflow-y-auto">
        {tab === "props" ? <PropertiesPanelInner /> : <TokenEditor />}
      </div>
    </aside>
  );
}
