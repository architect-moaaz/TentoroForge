"use client";

import { useCallback } from "react";
import {
  Rows3, Columns3, LayoutGrid, Type, MousePointerClick,
  Table, FileInput, Square, Image, CircleUser, Tag, BarChart3,
  Inbox, TextCursorInput, AlignLeft, ChevronDownSquare, ToggleRight,
  CheckSquare, Calendar, GitBranch, Repeat, Minus, Hash, Star,
} from "lucide-react";
import { useIREditorStore, type IRNode, type NodePath } from "@/stores/ir-editor";

// ---------------------------------------------------------------------------
// Component templates (default node for each type)
// ---------------------------------------------------------------------------

interface PaletteItem {
  type: string;
  label: string;
  icon: typeof Rows3;
  category: "layout" | "content" | "input" | "composite" | "control";
  template: IRNode;
}

const PALETTE_ITEMS: PaletteItem[] = [
  // Layout
  { type: "Stack", label: "Stack", icon: Rows3, category: "layout",
    template: { node: "Stack", gap: "md", children: [] } },
  { type: "Row", label: "Row", icon: Columns3, category: "layout",
    template: { node: "Row", gap: "md", align: "center", children: [] } },
  { type: "Grid", label: "Grid", icon: LayoutGrid, category: "layout",
    template: { node: "Grid", columns: 2, gap: "md", children: [] } },
  { type: "Divider", label: "Divider", icon: Minus, category: "layout",
    template: { node: "Divider" } },

  // Content
  { type: "Text", label: "Text", icon: Type, category: "content",
    template: { node: "Text", content: "Text", typography: "body" } },
  { type: "Button", label: "Button", icon: MousePointerClick, category: "content",
    template: { node: "Button", label: "Button", variant: "primary" } },
  { type: "Badge", label: "Badge", icon: Tag, category: "content",
    template: { node: "Badge", content: "Badge" } },
  { type: "Image", label: "Image", icon: Image, category: "content",
    template: { node: "Image", src: "", alt: "Image" } },
  { type: "Avatar", label: "Avatar", icon: CircleUser, category: "content",
    template: { node: "Avatar", name: "User", size: "md" } },
  { type: "Icon", label: "Icon", icon: Star, category: "content",
    template: { node: "Icon", name: "star", size: "md" } },
  { type: "StatCard", label: "Stat Card", icon: BarChart3, category: "content",
    template: { node: "StatCard", label: "Stat", value: "0", format: "number" } },
  { type: "EmptyState", label: "Empty State", icon: Inbox, category: "content",
    template: { node: "EmptyState", icon: "inbox", message: "No items found" } },

  // Input
  { type: "TextInput", label: "Text Input", icon: TextCursorInput, category: "input",
    template: { node: "TextInput", bind: "state:", label: "Label", placeholder: "Enter value..." } },
  { type: "TextArea", label: "Text Area", icon: AlignLeft, category: "input",
    template: { node: "TextArea", bind: "state:", label: "Label", rows: 3 } },
  { type: "Select", label: "Select", icon: ChevronDownSquare, category: "input",
    template: { node: "Select", bind: "state:", label: "Label", options: [{ value: "a", label: "Option A" }, { value: "b", label: "Option B" }] } },
  { type: "Checkbox", label: "Checkbox", icon: CheckSquare, category: "input",
    template: { node: "Checkbox", bind: "state:", label: "Check me" } },
  { type: "Toggle", label: "Toggle", icon: ToggleRight, category: "input",
    template: { node: "Toggle", bind: "state:", label: "Enable" } },
  { type: "DatePicker", label: "Date Picker", icon: Calendar, category: "input",
    template: { node: "DatePicker", bind: "state:", label: "Date" } },

  // Composite
  { type: "Card", label: "Card", icon: Square, category: "composite",
    template: { node: "Card", padding: "md", children: [{ node: "Text", content: "Card content" }] } },
  { type: "DataTable", label: "Data Table", icon: Table, category: "composite",
    template: { node: "DataTable", data: "source:", columns: [{ field: "name", header: "Name" }] } },
  { type: "Form", label: "Form", icon: FileInput, category: "composite",
    template: { node: "Form", bind: "state:form", onSubmit: { type: "toast", variant: "success", message: "Submitted!" }, fields: [] } },

  // Control
  { type: "Slot", label: "Conditional", icon: GitBranch, category: "control",
    template: { node: "Slot", if: "true", then: { node: "Text", content: "Shown" } } },
  { type: "Repeater", label: "Repeater", icon: Repeat, category: "control",
    template: { node: "Repeater", data: "source:", itemKey: "id", template: { node: "Text", content: "{{item.name}}" } } },
];

const CATEGORIES = [
  { key: "layout", label: "Layout" },
  { key: "content", label: "Content" },
  { key: "input", label: "Input" },
  { key: "composite", label: "Composite" },
  { key: "control", label: "Control" },
] as const;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ComponentPalette() {
  const selectedPath = useIREditorStore((s) => s.selectedPath);
  const applyOps = useIREditorStore((s) => s.applyOps);

  const handleAdd = useCallback(
    (item: PaletteItem) => {
      // Add as child of selected node (or root if nothing selected)
      const targetPath = selectedPath || [];
      const page = useIREditorStore.getState().getActivePage();
      if (!page) return;

      // Find the target node
      let target = page.root;
      for (const idx of targetPath) {
        if (Array.isArray(target.children) && target.children[idx]) {
          target = target.children[idx];
        }
      }

      // If target can accept children, add as child; otherwise add as sibling
      const canAcceptChildren = Array.isArray(target.children) ||
        ["Stack", "Row", "Grid", "Card", "AsyncSlot", "ModalTrigger"].includes(target.node);

      if (canAcceptChildren) {
        const childCount = Array.isArray(target.children) ? target.children.length : 0;
        applyOps([{
          type: "addChild",
          path: targetPath,
          index: childCount,
          node: structuredClone(item.template),
        }]);
      } else if (targetPath.length > 0) {
        // Add as sibling after the selected node
        const parentPath = targetPath.slice(0, -1);
        const index = targetPath[targetPath.length - 1] + 1;
        applyOps([{
          type: "addChild",
          path: parentPath,
          index,
          node: structuredClone(item.template),
        }]);
      }
    },
    [selectedPath, applyOps],
  );

  // Drag start handler
  const handleDragStart = useCallback(
    (e: React.DragEvent, item: PaletteItem) => {
      const data = JSON.stringify({
        source: "palette",
        nodeType: item.type,
        template: item.template,
      });
      e.dataTransfer.setData("text/plain", data);
      e.dataTransfer.setData("application/ir-node", data);
      e.dataTransfer.effectAllowed = "copyMove";
      // Set a drag image
      const el = e.currentTarget as HTMLElement;
      e.dataTransfer.setDragImage(el, 20, 20);
    },
    [],
  );

  return (
    <div className="p-2 space-y-3 overflow-y-auto h-full">
      {CATEGORIES.map((cat) => {
        const items = PALETTE_ITEMS.filter((i) => i.category === cat.key);
        return (
          <div key={cat.key}>
            <div className="text-[10px] font-semibold uppercase text-muted-foreground mb-1 px-1">
              {cat.label}
            </div>
            <div className="grid grid-cols-2 gap-1">
              {items.map((item) => {
                const Icon = item.icon;
                return (
                  <div
                    key={item.type}
                    className="flex items-center gap-1.5 px-2 py-1.5 text-xs rounded border border-transparent hover:border-border hover:bg-muted/50 cursor-grab active:cursor-grabbing transition-colors select-none"
                    onClick={() => handleAdd(item)}
                    draggable={true}
                    onDragStart={(e) => handleDragStart(e, item)}
                    title={`Add ${item.label}`}
                    role="button"
                    tabIndex={0}
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">{item.label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
