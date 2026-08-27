"use client";

/**
 * DesignEditor — GrapeJS-based visual editor for annotated HTML.
 *
 * Loads annotated HTML from the backend, provides a visual editing canvas,
 * and compiles back to TSX on save.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import GjsEditor, { Canvas } from "@grapesjs/react";
import type { Editor } from "grapesjs";
import "grapesjs/dist/css/grapes.min.css";

import { useDesignEditor } from "@/hooks/useDesignEditor";
import { useDesignEditorStore } from "@/stores/design-editor";
import { getEditorConfig, registerCustomComponents, setupCanvasTailwind, DEVICES } from "./grapesjs-config";
import { registerLayoutBlocks } from "./blocks/layout-blocks";
import { registerContentBlocks } from "./blocks/content-blocks";
import { registerDataBlocks } from "./blocks/data-blocks";
import { registerSlotBlocks } from "./blocks/slot-blocks";
import { registerInputBlocks } from "./blocks/input-blocks";
import { registerNavigationBlocks } from "./blocks/navigation-blocks";
import { AnnotationPanel } from "./panels/AnnotationPanel";
import { StylePanel } from "./panels/StylePanel";
import { ComponentPalette } from "./ComponentPalette";
import { DataBindingPanel } from "./panels/DataBindingPanel";
import { WorkflowBindingPanel } from "./panels/WorkflowBindingPanel";
import { PageFlowPanel } from "./panels/PageFlowPanel";
import { ComponentTree } from "@/components/ir-editor/ComponentTree";
import { useIREditorStore } from "@/stores/ir-editor";

// Icons
import {
  Monitor, Tablet, Smartphone, Save, Play, Undo2, Redo2,
  ChevronDown, Layers, PaintBucket, Code2, PanelLeftClose, PanelRightClose,
  Database, Workflow, GitBranch, Eye, TreePine,
} from "lucide-react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface DesignEditorProps {
  projectId: string;
  /** Called after a successful compile — switches to Visual Editor on the compiled route */
  onCompiled?: (route: string) => void;
}

export function DesignEditor({ projectId, onCompiled }: DesignEditorProps) {
  const editorRef = useRef<Editor | null>(null);
  const [editorReady, setEditorReady] = useState(false);
  const [leftPanelOpen, setLeftPanelOpen] = useState(true);
  const [leftTab, setLeftTab] = useState<"blocks" | "tree">("tree");
  const [rightPanelOpen, setRightPanelOpen] = useState(true);
  const [rightTab, setRightTab] = useState<"annotations" | "data" | "workflows" | "flow" | "styles" | "layers">("annotations");

  // Load IR into store so ComponentTree / ComponentPalette work
  const loadIR = useIREditorStore((s) => s.loadIR);
  useEffect(() => {
    fetch(`${API_BASE_URL}/api/projects/${projectId}/ir`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (data) loadIR(data, projectId); })
      .catch(() => {});
  }, [projectId, loadIR]);

  const { loadDesign, saveDesign, compileDesign, activePage, pages } = useDesignEditor(projectId);
  const {
    status, statusMessage, devicePreview, isDirty,
    activePageId, setActivePageId, setDevicePreview, updatePageHtml,
    lastCompileResult,
  } = useDesignEditorStore();

  // Load design on mount
  useEffect(() => {
    loadDesign();
  }, [loadDesign]);

  // Load page content into GrapeJS when active page changes
  useEffect(() => {
    if (!editorReady || !editorRef.current || !activePage) return;
    const editor = editorRef.current;

    // Extract body content from the full HTML document
    const bodyMatch = activePage.html.match(/<body[^>]*>([\s\S]*)<\/body>/i);
    const bodyContent = bodyMatch ? bodyMatch[1] : activePage.html;

    editor.setComponents(bodyContent);
    if (activePage.css) {
      editor.setStyle(activePage.css);
    }
  }, [editorReady, activePage]);

  // GrapeJS editor init callback
  const onEditor = useCallback((editor: Editor) => {
    editorRef.current = editor;

    // Register custom components, blocks, and Tailwind refresh
    registerCustomComponents(editor);
    setupCanvasTailwind(editor);
    registerLayoutBlocks(editor);
    registerContentBlocks(editor);
    registerDataBlocks(editor);
    registerSlotBlocks(editor);
    registerInputBlocks(editor);
    registerNavigationBlocks(editor);

    // Set up devices
    DEVICES.forEach((d) => {
      editor.Devices.add({ id: d.id, name: d.name, width: d.width });
    });

    // Track changes
    editor.on("change:changesCount", () => {
      if (!activePageId) return;
      const html = editor.getHtml();
      const css = editor.getCss();
      updatePageHtml(activePageId, html, css || undefined);
    });

    setEditorReady(true);
  }, [activePageId, updatePageHtml]);

  // Device preview handler
  const handleDeviceChange = useCallback((device: typeof devicePreview) => {
    setDevicePreview(device);
    if (editorRef.current) {
      const deviceMap = { desktop: "Desktop", tablet: "Tablet", mobile: "Mobile" };
      editorRef.current.Devices.select(deviceMap[device]);
    }
  }, [setDevicePreview]);

  // Undo/Redo
  const handleUndo = useCallback(() => editorRef.current?.UndoManager.undo(), []);
  const handleRedo = useCallback(() => editorRef.current?.UndoManager.redo(), []);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        saveDesign();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "z") {
        e.preventDefault();
        if (e.shiftKey) {
          handleRedo();
        } else {
          handleUndo();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [saveDesign, handleUndo, handleRedo]);

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b px-4 h-12 shrink-0">
        {/* Left: Page selector */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setLeftPanelOpen(!leftPanelOpen)}
            className="p-1.5 rounded hover:bg-muted"
            title={leftPanelOpen ? "Hide blocks" : "Show blocks"}
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>

          <div className="relative">
            <select
              className="appearance-none bg-transparent border rounded-lg px-3 py-1.5 pr-7 text-sm font-medium max-w-[220px] truncate"
              value={activePageId || ""}
              onChange={(e) => setActivePageId(e.target.value)}
            >
              {(() => {
                // Group pages by entity (first segment of route)
                const groups = new Map<string, typeof pages>();
                const standalone: typeof pages = [];
                for (const p of pages) {
                  const seg = p.route.split("/").filter(Boolean)[0] || "";
                  if (seg === "dashboard" || seg === "login" || seg === "signup" || !seg) {
                    standalone.push(p);
                  } else {
                    const group = groups.get(seg) || [];
                    group.push(p);
                    groups.set(seg, group);
                  }
                }
                const formatTitle = (p: typeof pages[0]) => {
                  const t = p.title || p.route;
                  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
                };
                return (
                  <>
                    {standalone.map((p) => (
                      <option key={p.pageId} value={p.pageId}>{formatTitle(p)}</option>
                    ))}
                    {Array.from(groups.entries()).map(([group, groupPages]) => (
                      <optgroup key={group} label={group.replace(/_/g, " ").replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}>
                        {groupPages.map((p) => (
                          <option key={p.pageId} value={p.pageId}>{formatTitle(p)}</option>
                        ))}
                      </optgroup>
                    ))}
                  </>
                );
              })()}
            </select>
            <ChevronDown className="absolute right-1.5 top-1/2 -translate-y-1/2 h-3 w-3 pointer-events-none text-muted-foreground" />
          </div>
        </div>

        {/* Center: Device preview + Undo/Redo */}
        <div className="flex items-center gap-1">
          <button
            onClick={handleUndo}
            className="p-1.5 rounded hover:bg-muted"
            title="Undo (Ctrl+Z)"
          >
            <Undo2 className="h-4 w-4" />
          </button>
          <button
            onClick={handleRedo}
            className="p-1.5 rounded hover:bg-muted"
            title="Redo (Ctrl+Shift+Z)"
          >
            <Redo2 className="h-4 w-4" />
          </button>

          <div className="w-px h-5 bg-border mx-2" />

          {[
            { key: "desktop" as const, icon: Monitor, label: "Desktop" },
            { key: "tablet" as const, icon: Tablet, label: "Tablet" },
            { key: "mobile" as const, icon: Smartphone, label: "Mobile" },
          ].map(({ key, icon: Icon, label }) => (
            <button
              key={key}
              onClick={() => handleDeviceChange(key)}
              className={`p-1.5 rounded ${
                devicePreview === key ? "bg-primary text-primary-foreground" : "hover:bg-muted"
              }`}
              title={label}
            >
              <Icon className="h-4 w-4" />
            </button>
          ))}
        </div>

        {/* Right: Save + Compile */}
        <div className="flex items-center gap-2">
          {isDirty && (
            <span className="text-xs text-muted-foreground">Unsaved changes</span>
          )}

          <button
            onClick={saveDesign}
            disabled={!isDirty || status === "saving"}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-muted disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            Save
          </button>

          <button
            onClick={async () => {
              const result = await compileDesign();
              if (result && !result.errors?.length && onCompiled) {
                const route = activePage?.route || result.pages?.[0]?.route || "/";
                onCompiled(route);
              }
            }}
            disabled={status === "compiling"}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
          >
            <Play className="h-3.5 w-3.5" />
            {status === "compiling" ? "Compiling..." : "Compile & Preview"}
          </button>

          <button
            onClick={() => setRightPanelOpen(!rightPanelOpen)}
            className="p-1.5 rounded hover:bg-muted"
            title={rightPanelOpen ? "Hide panel" : "Show panel"}
          >
            <PanelRightClose className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Status bar */}
      {statusMessage && (
        <div className={`px-4 py-1.5 text-xs ${
          status === "error" ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground"
        }`}>
          {statusMessage}
        </div>
      )}

      {/* Compile result */}
      {lastCompileResult && lastCompileResult.errors.length > 0 && (
        <div className="px-4 py-2 bg-destructive/10 text-destructive text-xs space-y-1">
          {lastCompileResult.errors.map((err, i) => (
            <div key={i}>{err}</div>
          ))}
        </div>
      )}

      {/* Main editor area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left panel: Structure tree + block palettes */}
        {leftPanelOpen && (
          <div className="w-[280px] shrink-0 border-r flex flex-col bg-background overflow-hidden">
            {/* Tab strip */}
            <div className="flex border-b shrink-0">
              {[
                { id: "tree" as const, icon: TreePine, label: "Tree" },
                { id: "blocks" as const, icon: Layers, label: "Blocks" },
              ].map(({ id, icon: Icon, label }) => (
                <button
                  key={id}
                  onClick={() => setLeftTab(id)}
                  className={`flex-1 flex items-center justify-center gap-1 py-1.5 text-[11px] font-medium border-b-2 transition-colors ${
                    leftTab === id
                      ? "border-primary text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Icon className="h-3 w-3" />
                  {label}
                </button>
              ))}
            </div>
            {/* Tab content */}
            <div className="flex-1 overflow-y-auto">
              {leftTab === "tree" && <ComponentTree />}
              {leftTab === "blocks" && <ComponentPalette editor={editorRef.current} />}
            </div>
          </div>
        )}

        {/* Canvas */}
        <div className="flex-1 overflow-hidden">
          <GjsEditor
            grapesjs="https://unpkg.com/grapesjs"
            options={{
              ...getEditorConfig(),
              container: "#gjs-canvas",
            }}
            onEditor={onEditor}
          >
            <Canvas />
          </GjsEditor>
        </div>

        {/* Right panel: Annotations / Styles / Layers */}
        {rightPanelOpen && (
          <div className="w-[320px] border-l overflow-y-auto shrink-0">
            {/* Tab buttons */}
            <div className="flex flex-wrap border-b">
              {[
                { key: "annotations" as const, icon: Code2, label: "Props" },
                { key: "data" as const, icon: Database, label: "Data" },
                { key: "workflows" as const, icon: Workflow, label: "Flows" },
                { key: "flow" as const, icon: GitBranch, label: "Pages" },
                { key: "styles" as const, icon: PaintBucket, label: "Styles" },
                { key: "layers" as const, icon: Layers, label: "Layers" },
              ].map(({ key, icon: Icon, label }) => (
                <button
                  key={key}
                  onClick={() => setRightTab(key)}
                  className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-2 text-xs font-medium border-b-2 ${
                    rightTab === key
                      ? "border-primary text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </button>
              ))}
            </div>

            {/* Panel content */}
            {rightTab === "annotations" && (
              <AnnotationPanel editor={editorRef.current} />
            )}
            {rightTab === "data" && (
              <DataBindingPanel editor={editorRef.current} projectId={projectId} />
            )}
            {rightTab === "workflows" && (
              <WorkflowBindingPanel editor={editorRef.current} projectId={projectId} />
            )}
            {rightTab === "flow" && (
              <PageFlowPanel
                projectId={projectId}
                pages={pages}
                activePageId={activePageId}
                onSelectPage={(pageId) => setActivePageId(pageId)}
              />
            )}
            {rightTab === "styles" && (
              <StylePanel editor={editorRef.current} />
            )}
            {rightTab === "layers" && (
              <div className="p-3 text-xs text-muted-foreground">
                Use the Tree tab on the left panel to view the component hierarchy.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default DesignEditor;
