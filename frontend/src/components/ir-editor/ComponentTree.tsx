"use client";

import { useState, useCallback } from "react";
import {
  ChevronRight,
  ChevronDown,
  Rows3,
  Columns3,
  LayoutGrid,
  Type,
  Image,
  CircleUser,
  Tag,
  MousePointerClick,
  BarChart3,
  Inbox,
  Table,
  FileInput,
  Square,
  PanelTop,
  GitBranch,
  Repeat,
  CloudDownload,
  Code,
  Minus,
  TextCursorInput,
  AlignLeft,
  ChevronDownSquare,
  CheckSquare,
  ToggleRight,
  CircleDot,
  Calendar,
  Upload,
  Hash,
  Star,
  Loader,
  Space,
  Puzzle,
  SlidersHorizontal,
  Palette,
  FileText,
  ChevronsDownUp,
  PanelTopOpen,
} from "lucide-react";
import {
  useIREditorStore,
  type IRNode,
  type NodePath,
  getNodeLabel,
} from "@/stores/ir-editor";

// ---------------------------------------------------------------------------
// Icon map for node types
// ---------------------------------------------------------------------------

const NODE_ICONS: Record<string, typeof Rows3> = {
  Stack: Rows3,
  Row: Columns3,
  Grid: LayoutGrid,
  Spacer: Space,
  Divider: Minus,
  Text: Type,
  Icon: Star,
  Image: Image,
  Avatar: CircleUser,
  Badge: Tag,
  Tag: Hash,
  Button: MousePointerClick,
  StatCard: BarChart3,
  EmptyState: Inbox,
  Skeleton: Loader,
  TextInput: TextCursorInput,
  TextArea: AlignLeft,
  Select: ChevronDownSquare,
  Checkbox: CheckSquare,
  Toggle: ToggleRight,
  RadioGroup: CircleDot,
  DatePicker: Calendar,
  FilePicker: Upload,
  RichTextEditor: FileText,
  Slider: SlidersHorizontal,
  ColorPicker: Palette,
  DataTable: Table,
  Form: FileInput,
  Card: Square,
  Tabs: PanelTop,
  ModalTrigger: PanelTopOpen,
  Accordion: ChevronsDownUp,
  Chart: BarChart3,
  Slot: GitBranch,
  Repeater: Repeat,
  AsyncSlot: CloudDownload,
  Custom: Code,
  FragmentRef: Puzzle,
};

// ---------------------------------------------------------------------------
// Tree node component
// ---------------------------------------------------------------------------

interface TreeNodeProps {
  node: IRNode;
  path: NodePath;
  depth: number;
}

function TreeNode({ node, path, depth }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(depth < 3);
  const selectedPath = useIREditorStore((s) => s.selectedPath);
  const hoveredPath = useIREditorStore((s) => s.hoveredPath);
  const selectNode = useIREditorStore((s) => s.selectNode);
  const hoverNode = useIREditorStore((s) => s.hoverNode);
  const applyOps = useIREditorStore((s) => s.applyOps);

  const isSelected = selectedPath?.join(",") === path.join(",");
  const isHovered = hoveredPath?.join(",") === path.join(",");

  const children = getAllChildren(node);
  const hasChildren = children.length > 0;

  const Icon = NODE_ICONS[node.node] || Code;
  const label = getNodeLabel(node);

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      selectNode(path);
    },
    [path, selectNode],
  );

  const handleToggle = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      setExpanded((v) => !v);
    },
    [],
  );

  const handleDelete = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        if (path.length === 0) return; // can't delete root
        const parentPath = path.slice(0, -1);
        const index = path[path.length - 1];
        applyOps([{ type: "removeChild", path: parentPath, index }]);
        selectNode(null);
      }
    },
    [path, applyOps, selectNode],
  );

  return (
    <div>
      <div
        className={`flex items-center gap-1 px-2 py-0.5 cursor-pointer text-sm select-none rounded-sm ${
          isSelected
            ? "bg-primary/10 text-primary"
            : isHovered
              ? "bg-muted"
              : "hover:bg-muted/50"
        }`}
        style={{ paddingLeft: `${depth * 16 + 4}px` }}
        onClick={handleClick}
        onMouseEnter={() => hoverNode(path)}
        onMouseLeave={() => hoverNode(null)}
        onKeyDown={handleDelete}
        tabIndex={0}
      >
        {/* Expand/collapse toggle */}
        <span
          className="w-4 h-4 flex items-center justify-center shrink-0"
          onClick={handleToggle}
        >
          {hasChildren ? (
            expanded ? (
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3 w-3 text-muted-foreground" />
            )
          ) : null}
        </span>

        {/* Node icon */}
        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />

        {/* Node label */}
        <span className="truncate">{label}</span>
      </div>

      {/* Children */}
      {hasChildren && expanded && (
        <div>
          {children.map((child, i) => (
            <TreeNode
              key={`${path.join("-")}-${i}`}
              node={child.node}
              path={child.path}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Get all child nodes (including named slots)
// ---------------------------------------------------------------------------

function getAllChildren(
  node: IRNode,
): Array<{ node: IRNode; path: number[]; slotName?: string }> {
  const result: Array<{ node: IRNode; path: number[]; slotName?: string }> = [];

  // children array (main slot)
  if (Array.isArray(node.children)) {
    node.children.forEach((child, i) => {
      if (child && typeof child === "object" && "node" in child) {
        result.push({ node: child, path: [i] });
      }
    });
  }

  // Named slots (template, emptyState, header, footer, etc.)
  const namedSlots = [
    "template",
    "emptyState",
    "header",
    "footer",
    "media",
    "loading",
    "error",
    "then",
    "else",
  ];
  for (const slot of namedSlots) {
    const slotNode = node[slot];
    if (slotNode && typeof slotNode === "object" && "node" in (slotNode as object)) {
      // Named slots aren't indexed in children — display them with a label
      // For tree purposes, we don't give them a numeric path
    }
  }

  // Slot cases
  if (node.cases && typeof node.cases === "object") {
    // Display cases as children for tree navigation
  }

  return result;
}

// ---------------------------------------------------------------------------
// Main component tree panel
// ---------------------------------------------------------------------------

export function ComponentTree() {
  const page = useIREditorStore((s) => s.getActivePage());

  if (!page) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        No page selected
      </div>
    );
  }

  return (
    <div className="py-1 overflow-y-auto h-full text-xs">
      <TreeNode node={page.root} path={[]} depth={0} />
    </div>
  );
}
