"use client";

import { useState, useCallback } from "react";
import {
  ChevronRight,
  ChevronDown,
  LayoutDashboard,
  Navigation,
  Rows3,
  Square,
  Footprints,
  Plus,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVisualEditorStore } from "@/stores/visual-editor";
import type { SectionNode } from "@/types/visual-editor";
import { ComponentPalette } from "./ComponentPalette";

const TAG_ICONS: Record<string, typeof Square> = {
  header: LayoutDashboard,
  nav: Navigation,
  section: Rows3,
  main: Rows3,
  article: Rows3,
  aside: Rows3,
  footer: Footprints,
};

function getLabel(node: SectionNode): string {
  if (node.source?.component) return node.source.component;
  if (node.textPreview) return node.textPreview;
  return `<${node.tagName}>`;
}

interface TreeItemProps {
  node: SectionNode;
  onSelect: (node: SectionNode) => void;
  onHover: (node: SectionNode) => void;
  onHoverEnd: () => void;
  selectedId: string | null;
  dragHandlers?: {
    onDragStart: (e: React.DragEvent, node: SectionNode) => void;
    onDragOver: (e: React.DragEvent, node: SectionNode) => void;
    onDragLeave: (e: React.DragEvent) => void;
    onDrop: (e: React.DragEvent, node: SectionNode) => void;
  };
  dropIndicator?: { id: string; position: "before" | "after" } | null;
}

function TreeItem({ node, onSelect, onHover, onHoverEnd, selectedId, dragHandlers, dropIndicator }: TreeItemProps) {
  const [expanded, setExpanded] = useState(node.depth < 2);
  const hasChildren = node.children && node.children.length > 0;
  const Icon = TAG_ICONS[node.tagName] || Square;
  const isSelected = selectedId === node.id;
  const isRoot = node.depth === 0;

  return (
    <div>
      {dropIndicator?.id === node.id && dropIndicator.position === "before" && (
        <div className="h-0.5 bg-blue-500 mx-2" />
      )}
      <div
        className={`flex items-center gap-1 px-2 py-1 text-sm cursor-pointer hover:bg-muted/50 transition-colors ${
          isSelected ? "bg-accent text-accent-foreground" : ""
        }`}
        style={{ paddingLeft: `${8 + node.depth * 16}px` }}
        onClick={() => onSelect(node)}
        onMouseEnter={() => onHover(node)}
        onMouseLeave={onHoverEnd}
        draggable={isRoot}
        onDragStart={isRoot && dragHandlers ? (e) => dragHandlers.onDragStart(e, node) : undefined}
        onDragOver={isRoot && dragHandlers ? (e) => dragHandlers.onDragOver(e, node) : undefined}
        onDragLeave={isRoot && dragHandlers ? (e) => dragHandlers.onDragLeave(e) : undefined}
        onDrop={isRoot && dragHandlers ? (e) => dragHandlers.onDrop(e, node) : undefined}
      >
        {hasChildren ? (
          <button
            className="p-0.5 hover:bg-muted rounded"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
          >
            {expanded ? (
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3 w-3 text-muted-foreground" />
            )}
          </button>
        ) : (
          <span className="w-4" />
        )}
        <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        <span className="truncate flex-1">{getLabel(node)}</span>
        {node.source && (
          <span className="text-[9px] text-muted-foreground font-mono shrink-0">
            {node.source.file.split("/").pop()}:{node.source.line}
          </span>
        )}
      </div>
      {dropIndicator?.id === node.id && dropIndicator.position === "after" && (
        <div className="h-0.5 bg-blue-500 mx-2" />
      )}
      {expanded && hasChildren && node.children!.map((child) => (
        <TreeItem
          key={child.id}
          node={child}
          onSelect={onSelect}
          onHover={onHover}
          onHoverEnd={onHoverEnd}
          selectedId={selectedId}
        />
      ))}
    </div>
  );
}

interface SectionOutlinePanelProps {
  projectId: string;
  onScrollTo?: (xpath: string) => void;
  onHighlight?: (xpath: string) => void;
  onReorderSection?: (sourceXpath: string, targetXpath: string, position: "before" | "after") => void;
}

export function SectionOutlinePanel({ projectId, onScrollTo, onHighlight, onReorderSection }: SectionOutlinePanelProps) {
  const sectionTree = useVisualEditorStore((s) => s.sectionTree);
  const selectedSectionId = useVisualEditorStore((s) => s.selectedSectionId);
  const setSelectedSectionId = useVisualEditorStore((s) => s.setSelectedSectionId);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [dropIndicator, setDropIndicator] = useState<{ id: string; position: "before" | "after" } | null>(null);
  const [dragSourceId, setDragSourceId] = useState<string | null>(null);

  const handleSelect = useCallback(
    (node: SectionNode) => {
      setSelectedSectionId(node.id);
      onScrollTo?.(node.id);
    },
    [setSelectedSectionId, onScrollTo],
  );

  const handleHover = useCallback(
    (node: SectionNode) => {
      onHighlight?.(node.id);
    },
    [onHighlight],
  );

  const handleHoverEnd = useCallback(() => {
    // Clear highlight by sending empty
  }, []);

  const dragHandlers = {
    onDragStart: (e: React.DragEvent, node: SectionNode) => {
      e.dataTransfer.setData("section-xpath", node.id);
      e.dataTransfer.effectAllowed = "move";
      setDragSourceId(node.id);
    },
    onDragOver: (e: React.DragEvent, node: SectionNode) => {
      e.preventDefault();
      if (node.id === dragSourceId) return;
      const rect = (e.target as HTMLElement).getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      const position = e.clientY < midY ? "before" : "after";
      setDropIndicator({ id: node.id, position });
    },
    onDragLeave: (_e: React.DragEvent) => {
      setDropIndicator(null);
    },
    onDrop: (e: React.DragEvent, node: SectionNode) => {
      e.preventDefault();
      const sourceXpath = e.dataTransfer.getData("section-xpath");
      if (!sourceXpath || sourceXpath === node.id) return;
      const position = dropIndicator?.position || "after";
      onReorderSection?.(sourceXpath, node.id, position);
      setDropIndicator(null);
      setDragSourceId(null);
    },
  };

  return (
    <>
      <div className="w-[280px] shrink-0 border-r flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b shrink-0">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            Page Outline
          </span>
        </div>

        <div className="flex-1 overflow-y-auto">
          {sectionTree.length === 0 ? (
            <div className="px-3 py-8 text-center">
              <p className="text-xs text-muted-foreground">
                No sections detected. Load a page to see its structure.
              </p>
            </div>
          ) : (
            sectionTree.map((node) => (
              <TreeItem
                key={node.id}
                node={node}
                onSelect={handleSelect}
                onHover={handleHover}
                onHoverEnd={handleHoverEnd}
                selectedId={selectedSectionId}
                dragHandlers={dragHandlers}
                dropIndicator={dropIndicator}
              />
            ))
          )}
        </div>

        <div className="border-t p-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            className="w-full gap-1.5"
            onClick={() => setPaletteOpen(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            Add Section
          </Button>
        </div>
      </div>

      <ComponentPalette
        projectId={projectId}
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
      />
    </>
  );
}
