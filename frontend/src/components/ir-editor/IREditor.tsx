"use client";

import { useEffect, useCallback, useState } from "react";
import {
  Undo2, Redo2, Monitor, Tablet, Smartphone, Code2,
  ChevronDown, Save, Loader2, Layout,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useIREditorStore, type AppIR } from "@/stores/ir-editor";
import { ComponentTree } from "./ComponentTree";
import { ComponentPalette } from "./ComponentPalette";
import { PropertiesPanel } from "./PropertiesPanel";
import { IRCanvas } from "./IRCanvas";
import { IRRenderer } from "./renderer";

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

async function fetchIR(projectId: string): Promise<AppIR | null> {
  try {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/ir`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

async function saveIRToBackend(projectId: string, ir: AppIR): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/ir`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ir),
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Editor component
// ---------------------------------------------------------------------------

interface IREditorProps {
  projectId: string;
  /** Optional: load IR directly instead of fetching */
  initialIR?: AppIR;
}

export function IREditor({ projectId, initialIR }: IREditorProps) {
  const ir = useIREditorStore((s) => s.ir);
  const activePageId = useIREditorStore((s) => s.activePageId);
  const loadIR = useIREditorStore((s) => s.loadIR);
  const setActivePage = useIREditorStore((s) => s.setActivePage);
  const undo = useIREditorStore((s) => s.undo);
  const redo = useIREditorStore((s) => s.redo);
  const canUndo = useIREditorStore((s) => s.canUndo());
  const canRedo = useIREditorStore((s) => s.canRedo());
  const devicePreview = useIREditorStore((s) => s.devicePreview);
  const setDevicePreview = useIREditorStore((s) => s.setDevicePreview);
  const showCode = useIREditorStore((s) => s.showCode);
  const setShowCode = useIREditorStore((s) => s.setShowCode);
  const isDirty = useIREditorStore((s) => s.isDirty);
  const selectNode = useIREditorStore((s) => s.selectNode);
  const selectedPath = useIREditorStore((s) => s.selectedPath);
  const hoveredPath = useIREditorStore((s) => s.hoveredPath);
  const hoverNode = useIREditorStore((s) => s.hoverNode);
  const activePage = useIREditorStore((s) => s.getActivePage());

  const [leftTab, setLeftTab] = useState<"tree" | "palette">("tree");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(!initialIR);

  // Load IR on mount or when projectId changes
  useEffect(() => {
    // Reset store when switching projects
    const currentProjectId = useIREditorStore.getState().projectId;
    if (currentProjectId !== projectId) {
      useIREditorStore.getState().reset();
    }

    if (initialIR) {
      loadIR(initialIR, projectId);
      return;
    }
    setLoading(true);
    fetchIR(projectId).then((data) => {
      if (data) {
        loadIR(data, projectId);
      }
      // If data is null, store stays reset (ir = null) → shows "No IR" message
      setLoading(false);
    });
  }, [projectId, initialIR, loadIR]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "z" && e.shiftKey) {
        e.preventDefault();
        redo();
      }
      if (e.key === "Escape") {
        selectNode(null);
      }
      if ((e.key === "Delete" || e.key === "Backspace") && selectedPath && selectedPath.length > 0) {
        // Only if not focused on an input
        if ((e.target as HTMLElement).tagName !== "INPUT" && (e.target as HTMLElement).tagName !== "TEXTAREA") {
          e.preventDefault();
          const parentPath = selectedPath.slice(0, -1);
          const index = selectedPath[selectedPath.length - 1];
          useIREditorStore.getState().applyOps([{ type: "removeChild", path: parentPath, index }]);
          selectNode(null);
        }
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "d") {
        e.preventDefault();
        if (selectedPath && selectedPath.length > 0) {
          useIREditorStore.getState().applyOps([{ type: "duplicate", path: selectedPath }]);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [undo, redo, selectNode, selectedPath]);

  // Save handler
  const handleSave = useCallback(async () => {
    const currentIR = useIREditorStore.getState().ir;
    if (!currentIR) return;
    setSaving(true);
    await saveIRToBackend(projectId, currentIR);
    setSaving(false);
    useIREditorStore.setState({ isDirty: false });
  }, [projectId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading IR...
      </div>
    );
  }

  if (!ir) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
        <Layout className="h-8 w-8" />
        <p className="text-sm">No IR available for this project</p>
        <p className="text-xs">Generate the app first to create the IR</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* ── Toolbar ── */}
      <div className="flex items-center justify-between border-b px-3 py-1.5 bg-background shrink-0">
        <div className="flex items-center gap-2">
          {/* Page selector */}
          <Select value={activePageId || ""} onValueChange={setActivePage}>
            <SelectTrigger className="h-7 text-xs w-[180px]">
              <SelectValue placeholder="Select page" />
            </SelectTrigger>
            <SelectContent>
              {ir.pages.map((page) => (
                <SelectItem key={page.$id} value={page.$id}>
                  {page.title || page.$id} ({page.route})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="w-px h-5 bg-border" />

          {/* Undo/Redo */}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={undo}
            disabled={!canUndo}
            title="Undo (Cmd+Z)"
          >
            <Undo2 className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={redo}
            disabled={!canRedo}
            title="Redo (Cmd+Shift+Z)"
          >
            <Redo2 className="h-3.5 w-3.5" />
          </Button>
        </div>

        <div className="flex items-center gap-2">
          {/* Device preview */}
          <div className="flex items-center border rounded-md">
            <Button
              variant={devicePreview === "desktop" ? "secondary" : "ghost"}
              size="icon"
              className="h-7 w-7 rounded-none rounded-l-md"
              onClick={() => setDevicePreview("desktop")}
              title="Desktop"
            >
              <Monitor className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant={devicePreview === "tablet" ? "secondary" : "ghost"}
              size="icon"
              className="h-7 w-7 rounded-none"
              onClick={() => setDevicePreview("tablet")}
              title="Tablet"
            >
              <Tablet className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant={devicePreview === "mobile" ? "secondary" : "ghost"}
              size="icon"
              className="h-7 w-7 rounded-none rounded-r-md"
              onClick={() => setDevicePreview("mobile")}
              title="Mobile"
            >
              <Smartphone className="h-3.5 w-3.5" />
            </Button>
          </div>

          <div className="w-px h-5 bg-border" />

          {/* Code view toggle */}
          <Button
            variant={showCode ? "secondary" : "ghost"}
            size="sm"
            className="h-7 text-xs gap-1"
            onClick={() => setShowCode(!showCode)}
          >
            <Code2 className="h-3.5 w-3.5" />
            IR
          </Button>

          {/* Save */}
          <Button
            variant="default"
            size="sm"
            className="h-7 text-xs gap-1"
            onClick={handleSave}
            disabled={!isDirty || saving}
          >
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
            {saving ? "Saving" : isDirty ? "Save" : "Saved"}
          </Button>
        </div>
      </div>

      {/* ── Main content ── */}
      <div className="flex flex-1 overflow-hidden" onDragOver={(e) => e.preventDefault()}>
        {/* Left panel: tree + palette */}
        <div className="w-[280px] shrink-0 border-r flex flex-col bg-background">
          <div className="flex border-b shrink-0">
            <button
              className={`flex-1 px-3 py-1.5 text-xs font-medium ${
                leftTab === "tree" ? "border-b-2 border-primary text-primary" : "text-muted-foreground"
              }`}
              onClick={() => setLeftTab("tree")}
            >
              Tree
            </button>
            <button
              className={`flex-1 px-3 py-1.5 text-xs font-medium ${
                leftTab === "palette" ? "border-b-2 border-primary text-primary" : "text-muted-foreground"
              }`}
              onClick={() => setLeftTab("palette")}
            >
              Add
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {leftTab === "tree" ? <ComponentTree /> : <ComponentPalette />}
          </div>
        </div>

        {/* Center: canvas or code */}
        <div className="flex-1 overflow-hidden">
          {showCode ? (
            <div className="h-full overflow-auto bg-muted/30 p-4">
              <pre className="text-xs font-mono bg-background border rounded-lg p-4 overflow-auto max-h-full">
                {JSON.stringify(
                  activePage,
                  null,
                  2,
                )}
              </pre>
            </div>
          ) : activePage ? (
            <IRRenderer
              page={activePage as never}
              appIR={ir as never}
              editable
              selectedPath={selectedPath}
              hoveredPath={hoveredPath}
              onSelect={selectNode}
              onHover={hoverNode}
              className="min-h-full p-4 bg-white"
            />
          ) : (
            <IRCanvas />
          )}
        </div>

        {/* Right panel: properties */}
        <div className="w-[320px] shrink-0 border-l bg-background">
          <div className="border-b px-3 py-1.5">
            <span className="text-xs font-medium">Properties</span>
          </div>
          <PropertiesPanel />
        </div>
      </div>
    </div>
  );
}
