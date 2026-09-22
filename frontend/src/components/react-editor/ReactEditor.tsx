"use client";
/**
 * The visual React editor — the Editor tab (EDIT-001).
 *
 * Top bar · left panel (Pages / Add / Layers) · live canvas · settings drawer
 * · a Smith window beside the selection · a status bar. Everything edits the
 * page's React source through one transaction path in the store; the canvas
 * is the running app, so what is shown is what is saved.
 */
import { useEffect } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { usePreview } from "@/hooks/usePreview";
import { useEditorBreakpoint } from "@/hooks/useMediaQuery";

import { Canvas } from "./Canvas";
import { CodeDialog, HistoryDialog, ReadinessDialog } from "./Dialogs";
import { GuideDialog } from "./LeftPanel";
import { LeftPanel } from "./LeftPanel";
import { SettingsDrawer } from "./SettingsDrawer";
import { SmithWindow } from "./SmithWindow";
import { StatusBar } from "./StatusBar";
import { TopBar } from "./TopBar";
import { useEditorStore } from "./store";

export interface ReactEditorProps {
  /** The project's UUID — what the platform API is keyed by. */
  projectId: string;
}

export function ReactEditor({ projectId }: ReactEditorProps) {
  const init = useEditorStore((s) => s.init);
  const doc = useEditorStore((s) => s.doc);
  const loading = useEditorStore((s) => s.loading);
  const loadError = useEditorStore((s) => s.loadError);
  const pages = useEditorStore((s) => s.pages);
  const leftOpen = useEditorStore((s) => s.leftOpen);
  const rightOpen = useEditorStore((s) => s.rightOpen);
  const setLeftOpen = useEditorStore((s) => s.setLeftOpen);
  const setRightOpen = useEditorStore((s) => s.setRightOpen);
  const mode = useEditorStore((s) => s.mode);
  const { isDesktop } = useEditorBreakpoint();
  const preview = usePreview(projectId);

  useEffect(() => { void init(projectId); }, [projectId, init]);

  // The live-app source needs the dev server; learn whether it is up already.
  useEffect(() => { void preview.checkStatus(); }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keyboard shortcuts that belong to the editor shell (the canvas forwards its own).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = !!target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable);
      const mod = e.metaKey || e.ctrlKey;
      const s = useEditorStore.getState();
      if (mod && e.key.toLowerCase() === "z" && !typing) { e.preventDefault(); void (e.shiftKey ? s.redo() : s.undo()); }
      else if (mod && e.key === ".") { e.preventDefault(); setRightOpen(!s.rightOpen); }
      else if (mod && e.key === "/") { e.preventDefault(); setLeftOpen(!s.leftOpen); }
      else if (e.key === "Escape" && s.mode === "preview" && !s.previewApp) { s.setMode("design"); }
      else if (e.key === "Escape" && s.regionSelect) { s.setRegionSelect(false); }
      else if (mod && e.key.toLowerCase() === "p" && !typing) { e.preventDefault(); s.setMode(s.mode === "design" ? "preview" : "design"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setLeftOpen, setRightOpen]);

  if (loadError && !doc && !pages.length) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="max-w-md rounded-xl border border-border bg-card p-6 text-center">
          <AlertTriangle className="mx-auto mb-3 h-6 w-6 text-amber-500" />
          <p className="text-sm font-medium text-foreground">The editor could not open this project.</p>
          <p className="mt-1 text-sm text-muted-foreground">{loadError}</p>
          <Button className="mt-4" size="sm" onClick={() => void init(projectId)}>Try again</Button>
        </div>
      </div>
    );
  }

  const showLeft = leftOpen && (isDesktop || mode === "design");
  const showRight = rightOpen && mode === "design";

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <TopBar preview={preview} />
      <div className="relative flex min-h-0 flex-1">
        {showLeft && (
          <aside className={isDesktop ? "w-72 shrink-0 border-r border-border bg-card" : "absolute inset-y-0 left-0 z-30 w-80 border-r border-border bg-card shadow-xl"}>
            <LeftPanel onClose={() => setLeftOpen(false)} />
          </aside>
        )}
        <main className="relative flex min-w-0 flex-1 flex-col bg-muted/40">
          {loading && (
            <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/60">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}
          <Canvas preview={preview} />
          {mode === "design" && <SmithWindow />}
        </main>
        {showRight && (
          <aside className={isDesktop ? "w-80 shrink-0 border-l border-border bg-card" : "absolute inset-y-0 right-0 z-30 w-[22rem] border-l border-border bg-card shadow-xl"}>
            <SettingsDrawer onClose={() => setRightOpen(false)} />
          </aside>
        )}
      </div>
      <StatusBar />
      <ReadinessDialog />
      <HistoryDialog />
      <CodeDialog />
      <PendingGuide />
    </div>
  );
}

export default ReactEditor;


/** The questions a dropped chart, tile or form asks, opened by the drop itself. */
function PendingGuide() {
  const pending = useEditorStore((s) => s.pendingGuide);
  const setPendingGuide = useEditorStore((s) => s.setPendingGuide);
  const def = useEditorStore((s) => (pending ? s.doc?.registry.components.find((c) => c.id === pending.compId) ?? null : null));
  if (!pending || !def) return null;
  return <GuideDialog def={def} target={{ parentId: pending.parentId, index: pending.index }} onClose={() => setPendingGuide(null)} />;
}
