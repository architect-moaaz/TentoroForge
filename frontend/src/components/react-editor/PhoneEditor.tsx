"use client";
/**
 * The Editor's phone side (step 1): the phone app in a frame, with the panels that edit the application as a whole.
 *
 * Pages and the menu, and the look, are edits of the one Blueprint that the website and the phone app are both made from, so
 * these are the same panels the website side has. After each edit the phone is drawn again (`autoRedraw`). A part of a screen is
 * changed by hand from the picture (`editParts`): words, copy, delete. What is not here yet: looks, adding and moving parts.
 */
import { useEffect, useState } from "react";

import { PhonePreview } from "@/components/phone/PhonePreview";
import { cn } from "@/lib/utils";

import { PagesPanel } from "./PagesPanel";
import { AddPanel, LayersPanel, PhoneToolsProvider } from "./PhoneTools";
import { ThemePanel } from "./ThemePanel";
import { useEditorStore } from "./store";

type Tab = "pages" | "add" | "layers" | "look";

export function PhoneEditor({ projectId, onAskSmith }: { projectId: string; onAskSmith: () => void }) {
  const init = useEditorStore((s) => s.init);
  const [tab, setTab] = useState<Tab>("pages");

  // The same store the website side reads: it holds the pages, the menu and the look.
  useEffect(() => { void init(projectId); }, [projectId, init]);

  return (
    <PhoneToolsProvider projectId={projectId}>
    <div className="flex h-full min-h-0 bg-background text-foreground" data-testid="phone-editor">
      <aside className="flex w-72 shrink-0 flex-col border-r border-border bg-card">
        <div className="flex h-9 shrink-0 items-center border-b border-border px-1" role="tablist">
          {([["pages", "Pages"], ["add", "Add"], ["layers", "Layers"], ["look", "Look"]] as const).map(([key, label]) => (
            <button key={key} role="tab" aria-selected={tab === key} type="button" onClick={() => setTab(key)}
              className={cn("h-full border-b-2 px-3 text-xs font-medium",
                tab === key ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              {label}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {tab === "pages" ? <PagesPanel surface="phone" /> : tab === "add" ? <AddPanel /> : tab === "layers" ? <LayersPanel /> : <ThemePanel />}
        </div>
        <p className="shrink-0 border-t border-border p-2 text-[11px] text-muted-foreground">
          The phone is drawn again after each change. To change a part, use <strong>Select to change</strong> and click it. <strong>Add</strong> puts a ready part on the screen; <strong>Layers</strong> lists the parts to drag. For anything else, ask Smith.
        </p>
      </aside>
      <main className="min-w-0 flex-1 bg-muted/40">
        <PhonePreview projectId={projectId} onAskSmith={onAskSmith} autoRedraw editParts />
      </main>
    </div>
    </PhoneToolsProvider>
  );
}

export default PhoneEditor;
