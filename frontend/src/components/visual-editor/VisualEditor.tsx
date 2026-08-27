"use client";

import { useEffect, useCallback, useRef, useState } from "react";
import {
  ArrowLeft,
  Undo2,
  Monitor,
  Tablet,
  Smartphone,
  Loader2,
  ChevronDown,
  PanelLeft,
  PanelRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePreview } from "@/hooks/usePreview";
import { useVisualEdit } from "@/hooks/useVisualEdit";
import { useVisualEditorStore } from "@/stores/visual-editor";
import { CanvasFrame, type CanvasFrameHandle } from "./CanvasFrame";
import { AIEditInput } from "./AIEditInput";
import { ElementActionPopover } from "./ElementActionPopover";
import { SectionOutlinePanel } from "./SectionOutlinePanel";
import { ContextPanel } from "./ContextPanel";
import type { DeviceSize } from "@/types/visual-editor";
import { api } from "@/lib/api";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";

const DEVICE_ICONS: Record<DeviceSize, typeof Monitor> = {
  desktop: Monitor,
  tablet: Tablet,
  mobile: Smartphone,
};

const FALLBACK_ROUTES = ["/"];

interface PageInfo {
  id: string;
  name: string;
  route: string;
}

interface VisualEditorProps {
  projectId: string;
  /** Route to navigate to on mount — set by Design Editor after compile */
  initialRoute?: string;
  /** Called when user clicks "Edit Structure" — switches to Design Editor */
  onEditStructure?: () => void;
}

export function VisualEditor({ projectId, initialRoute, onEditStructure }: VisualEditorProps) {
  const aiInputRef = useRef<HTMLInputElement>(null);
  const canvasRef = useRef<CanvasFrameHandle>(null);
  const preview = usePreview(projectId);
  const visualEdit = useVisualEdit(projectId);
  const [routeDropdownOpen, setRouteDropdownOpen] = useState(false);
  const [pages, setPages] = useState<PageInfo[]>([]);
  const [pagesLoaded, setPagesLoaded] = useState(false);

  const [isUndoing, setIsUndoing] = useState(false);
  const [textEditModal, setTextEditModal] = useState<{ open: boolean; text: string }>({ open: false, text: "" });
  const textEditInputRef = useRef<HTMLInputElement>(null);

  const currentRoute = useVisualEditorStore((s) => s.currentRoute);
  const setCurrentRoute = useVisualEditorStore((s) => s.setCurrentRoute);
  const selectedElement = useVisualEditorStore((s) => s.selectedElement);
  const devicePreview = useVisualEditorStore((s) => s.devicePreview);
  const setDevicePreview = useVisualEditorStore((s) => s.setDevicePreview);
  const setShowActionPopover = useVisualEditorStore((s) => s.setShowActionPopover);
  const leftPanelOpen = useVisualEditorStore((s) => s.leftPanelOpen);
  const rightPanelOpen = useVisualEditorStore((s) => s.rightPanelOpen);
  const setLeftPanelOpen = useVisualEditorStore((s) => s.setLeftPanelOpen);
  const setRightPanelOpen = useVisualEditorStore((s) => s.setRightPanelOpen);

  // Register edit-complete callback — uses HMR-aware reload instead of full page reload
  useEffect(() => {
    visualEdit.setOnEditComplete(() => {
      canvasRef.current?.notifyEditComplete();
    });
    return () => visualEdit.setOnEditComplete(null);
  }, [visualEdit]);

  // Fetch project pages from API.
  // The endpoint can return one of two shapes (two routers share the URL):
  //   - DB-backed (pages.py): PageInfo[]
  //   - filesystem (output_projects.py): { paths: string[] }
  // Coerce both into PageInfo[] so the rest of the component is shape-stable.
  useEffect(() => {
    let cancelled = false;
    api
      .get<PageInfo[] | { paths: string[] }>(`/api/projects/${projectId}/pages`)
      .then((data) => {
        if (cancelled) return;
        const normalized: PageInfo[] = Array.isArray(data)
          ? data
          : ((data?.paths ?? []) as string[]).map((path) => ({
              id: path,
              name: path,
              route: `/${path}`,
            }));
        setPages(normalized);
        setPagesLoaded(true);
      })
      .catch(() => {
        if (!cancelled) setPagesLoaded(true);
      });
    return () => { cancelled = true; };
  }, [projectId]);

  // Derive route list: pages from API, falling back to "/"
  const routes = pagesLoaded && pages.length > 0
    ? pages.map((p) => p.route)
    : FALLBACK_ROUTES;

  // Sync initialRoute from Design Editor compile handoff
  useEffect(() => {
    if (initialRoute && initialRoute !== currentRoute) {
      setCurrentRoute(initialRoute);
    }
    // Only run when initialRoute prop changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialRoute]);

  // Auto-start preview on mount
  useEffect(() => {
    if (!preview.port && !preview.isStarting) {
      preview.checkStatus().then(() => {
        if (!preview.port) {
          preview.startPreview();
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-select root route if none selected
  useEffect(() => {
    if (!currentRoute && preview.port) {
      setCurrentRoute("/");
    }
  }, [currentRoute, preview.port, setCurrentRoute]);

  const handleBack = useCallback(() => {
    setCurrentRoute(null);
    useVisualEditorStore.getState().setSelectedElement(null);
    setShowActionPopover(false);
  }, [setCurrentRoute, setShowActionPopover]);

  const handleUndo = useCallback(async () => {
    setIsUndoing(true);
    try {
      await visualEdit.undo();
    } finally {
      setIsUndoing(false);
    }
  }, [visualEdit]);

  const handleClassChange = useCallback(
    (action: "add" | "remove" | "replace", cls: string, replaceCls?: string) => {
      if (!selectedElement?.source) return;
      visualEdit.directEdit({
        tailwind_edits: [
          {
            file: selectedElement.source.file,
            line: selectedElement.source.line,
            action,
            class_name: cls,
            replace_with: replaceCls,
          },
        ],
      });
    },
    [selectedElement, visualEdit],
  );

  const handleAIEdit = useCallback(
    (instruction: string, file?: string, line?: number, contextElement?: string) => {
      visualEdit.aiEdit({ instruction, file, line, context_element: contextElement });
    },
    [visualEdit],
  );

  const handleEditText = useCallback(() => {
    if (!selectedElement?.source) return;
    setTextEditModal({ open: true, text: selectedElement.textContent || "" });
    setShowActionPopover(false);
  }, [selectedElement, setShowActionPopover]);

  const handleTextEditSubmit = useCallback(() => {
    if (!selectedElement?.source) return;
    const newText = textEditModal.text;
    if (newText === selectedElement.textContent) {
      setTextEditModal({ open: false, text: "" });
      return;
    }
    visualEdit.directEdit({
      text_edits: [
        {
          file: selectedElement.source.file,
          line: selectedElement.source.line,
          old_text: selectedElement.textContent,
          new_text: newText,
        },
      ],
    });
    setTextEditModal({ open: false, text: "" });
  }, [selectedElement, visualEdit, textEditModal.text]);

  const handleAskAI = useCallback(() => {
    setShowActionPopover(false);
    // Focus the AI input bar
    setTimeout(() => aiInputRef.current?.focus(), 50);
  }, [setShowActionPopover]);

  const handleDeleteElement = useCallback(() => {
    if (!selectedElement?.source) return;
    const contextElement = `${selectedElement.tagName}${
      selectedElement.className
        ? "." + selectedElement.className.split(/\s+/).join(".")
        : ""
    }`;
    visualEdit.aiEdit({
      instruction: "Remove this element completely",
      file: selectedElement.source.file,
      line: selectedElement.source.line,
      context_element: contextElement,
    });
    setShowActionPopover(false);
  }, [selectedElement, visualEdit, setShowActionPopover]);

  const handleScrollTo = useCallback((xpath: string) => {
    canvasRef.current?.scrollTo?.(xpath);
  }, []);

  const handleHighlight = useCallback((xpath: string) => {
    canvasRef.current?.highlight?.(xpath);
  }, []);

  const handleReorderSection = useCallback(
    async (sourceXpath: string, targetXpath: string, position: "before" | "after") => {
      const sectionTree = useVisualEditorStore.getState().sectionTree;
      const findNode = (nodes: typeof sectionTree, xpath: string): typeof sectionTree[0] | null => {
        for (const n of nodes) {
          if (n.id === xpath) return n;
          if (n.children) {
            const found = findNode(n.children, xpath);
            if (found) return found;
          }
        }
        return null;
      };
      const sourceNode = findNode(sectionTree, sourceXpath);
      const targetNode = findNode(sectionTree, targetXpath);
      if (!sourceNode?.source || !targetNode?.source) return;

      await visualEdit.reorderSection?.({
        route: currentRoute || "/",
        source_file: sourceNode.source.file,
        source_line: sourceNode.source.line,
        target_file: targetNode.source.file,
        target_line: targetNode.source.line,
        position,
      });
    },
    [currentRoute, visualEdit],
  );

  // Helper to get display label for a route
  const getRouteLabel = (route: string) => {
    const page = pages.find((p) => p.route === route);
    return page ? `${page.name} (${route})` : route;
  };

  // Derive canvas content based on preview + route state
  const canvasContent = (() => {
    if (preview.isStarting && !preview.port) {
      return (
        <div className="flex flex-1 items-center justify-center gap-3 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Starting preview…</span>
        </div>
      );
    }
    if (!preview.port) {
      return (
        <div className="flex flex-1 items-center justify-center">
          <div className="text-center space-y-2">
            <p className="text-sm text-muted-foreground">Preview not running</p>
            <Button size="sm" onClick={() => preview.startPreview()}>
              Start Preview
            </Button>
          </div>
        </div>
      );
    }
    if (!currentRoute) {
      return (
        <div className="flex flex-1 flex-col items-center justify-center gap-3">
          <p className="text-sm text-muted-foreground">Select a page to start editing</p>
          <div className="flex flex-wrap gap-2 justify-center px-4">
            {routes.map((route) => (
              <Button
                key={route}
                variant="outline"
                size="sm"
                onClick={() => setCurrentRoute(route)}
              >
                {getRouteLabel(route)}
              </Button>
            ))}
          </div>
        </div>
      );
    }
    return (
      <CanvasFrame
        ref={canvasRef}
        previewPort={preview.port}
        projectId={projectId}
      />
    );
  })();

  return (
    <div className="flex h-full flex-col">
      {/* ── Toolbar — always visible ── */}
      <div className="flex items-center gap-2 border-b px-3 py-2 shrink-0">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={handleBack}
          title="Deselect page"
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>

        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => setLeftPanelOpen(!leftPanelOpen)}
          title={leftPanelOpen ? "Hide outline" : "Show outline"}
        >
          <PanelLeft className="h-4 w-4" />
        </Button>

        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={handleUndo}
          disabled={isUndoing || visualEdit.isEditing || !currentRoute}
          title="Undo last edit"
        >
          {isUndoing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Undo2 className="h-4 w-4" />
          )}
        </Button>

        {/* Edit Structure — jump back to Design / Build editor */}
        {onEditStructure && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1.5 text-xs"
            onClick={onEditStructure}
            title="Edit page structure"
          >
            <PanelLeft className="h-3.5 w-3.5" />
            Edit Structure
          </Button>
        )}

        {/* Route dropdown */}
        <div className="relative">
          <button
            className="flex items-center gap-1 rounded-md border px-2 py-1 text-sm font-medium hover:bg-muted transition-colors"
            onClick={() => setRouteDropdownOpen(!routeDropdownOpen)}
          >
            {currentRoute ? getRouteLabel(currentRoute) : <span className="text-muted-foreground">Select page…</span>}
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
          {routeDropdownOpen && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setRouteDropdownOpen(false)}
              />
              <div className="absolute top-full left-0 z-50 mt-1 rounded-md border bg-popover shadow-md py-1 min-w-[180px]">
                {routes.map((route) => (
                  <button
                    key={route}
                    className={`w-full px-3 py-1.5 text-left text-sm hover:bg-muted transition-colors ${
                      route === currentRoute ? "bg-muted font-medium" : ""
                    }`}
                    onClick={() => {
                      setCurrentRoute(route);
                      setRouteDropdownOpen(false);
                      setShowActionPopover(false);
                    }}
                  >
                    {getRouteLabel(route)}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="flex-1" />

        {/* Device toggle */}
        <div className="flex items-center gap-0.5 rounded-md border p-0.5">
          {(["desktop", "tablet", "mobile"] as DeviceSize[]).map((device) => {
            const Icon = DEVICE_ICONS[device];
            return (
              <Button
                key={device}
                variant={devicePreview === device ? "secondary" : "ghost"}
                size="icon"
                className="h-6 w-6"
                onClick={() => setDevicePreview(device)}
                title={device}
              >
                <Icon className="h-3.5 w-3.5" />
              </Button>
            );
          })}
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => setRightPanelOpen(!rightPanelOpen)}
          title={rightPanelOpen ? "Hide properties" : "Show properties"}
        >
          <PanelRight className="h-4 w-4" />
        </Button>
      </div>

      {/* ── 3-Panel Layout ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Section Outline */}
        {leftPanelOpen && currentRoute && (
          <SectionOutlinePanel
            projectId={projectId}
            onScrollTo={handleScrollTo}
            onHighlight={handleHighlight}
            onReorderSection={handleReorderSection}
          />
        )}

        {/* Center: Canvas + AI Input */}
        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="relative flex flex-1 flex-col overflow-hidden">
            {canvasContent}

            {/* Floating action popover — only meaningful when a route is active */}
            {currentRoute && (
              <ElementActionPopover
                onEditText={handleEditText}
                onAskAI={handleAskAI}
                onDeleteElement={handleDeleteElement}
                onStyleChange={handleClassChange}
              />
            )}
          </div>

          {/* AI input bar */}
          <AIEditInput
            ref={aiInputRef}
            onSubmit={handleAIEdit}
            isEditing={visualEdit.isEditing}
            progress={visualEdit.progress}
            onAbort={visualEdit.abort}
          />
        </div>

        {/* Right: Context/Properties Panel */}
        {rightPanelOpen && currentRoute && (
          <ContextPanel
            projectId={projectId}
            onClassChange={handleClassChange}
            onEditText={handleEditText}
            onAskAI={handleAskAI}
            onDeleteElement={handleDeleteElement}
            onAIEdit={(instruction) => {
              if (!selectedElement?.source) return;
              visualEdit.aiEdit({
                instruction,
                file: selectedElement.source.file,
                line: selectedElement.source.line,
              });
            }}
          />
        )}
      </div>

      {/* Text Edit Modal */}
      <Dialog
        open={textEditModal.open}
        onOpenChange={(open) => {
          if (!open) setTextEditModal({ open: false, text: "" });
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Edit Text</DialogTitle>
          </DialogHeader>
          <input
            ref={textEditInputRef}
            type="text"
            value={textEditModal.text}
            onChange={(e) => setTextEditModal((prev) => ({ ...prev, text: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleTextEditSubmit();
            }}
            autoFocus
            className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setTextEditModal({ open: false, text: "" })}>
              Cancel
            </Button>
            <Button size="sm" onClick={handleTextEditSubmit}>
              Apply
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
