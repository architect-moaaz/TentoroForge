"use client";

/**
 * Component Palette — styled to match the Workflow Node Palette.
 *
 * Gradient icon containers, two-level text (label + description),
 * drag-and-drop into the GrapeJS canvas.
 *
 * Drop target:
 *   - If a component is selected on the canvas → block is appended INSIDE it
 *   - Otherwise → block is added to the page root
 */

import { useCallback, useEffect, useState } from "react";
import type { Editor, Component } from "grapesjs";
import {
  Columns3, Rows3, LayoutGrid, Minus, PanelTop,
  Type, Heading1, Heading2, AlignLeft, Tag,
  Image, MousePointer, CreditCard, BarChart3, AlertCircle,
  TextCursorInput, AlignJustify, ListFilter, CheckSquare, ToggleRight,
  Calendar, Paperclip, SlidersHorizontal, Lock, Mail, Hash, Phone, Link2,
  Table2, FormInput, Repeat, Search,
  LayoutTemplate, FileInput, Grid3x3, Presentation,
  Navigation, Layers, ChevronRight, MoreHorizontal, List,
  Info, CheckCircle, AlertTriangle, XCircle, UserCircle, Activity,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Block definitions — matches GrapeJS blocks but with visual metadata
// ---------------------------------------------------------------------------

interface BlockDef {
  id: string;
  label: string;
  description: string;
  icon: React.ElementType;
  gradient: string;
  html: string;
}

interface CategoryDef {
  label: string;
  blocks: BlockDef[];
}

const CATEGORIES: CategoryDef[] = [
  {
    label: "Layout",
    blocks: [
      {
        id: "stack",
        label: "Stack (Column)",
        description: "Vertical flex container",
        icon: Rows3,
        gradient: "from-blue-400 to-blue-600",
        html: `<div class="flex flex-col gap-4 p-4" data-component="Stack"><p class="text-sm text-muted-foreground">Stack content</p></div>`,
      },
      {
        id: "row",
        label: "Row",
        description: "Horizontal flex container",
        icon: Columns3,
        gradient: "from-blue-500 to-indigo-600",
        html: `<div class="flex flex-row gap-4 items-center" data-component="Row"><div class="flex-1 p-2 border rounded">Column 1</div><div class="flex-1 p-2 border rounded">Column 2</div></div>`,
      },
      {
        id: "grid-2",
        label: "Grid (2 cols)",
        description: "Two-column grid layout",
        icon: LayoutGrid,
        gradient: "from-indigo-400 to-indigo-600",
        html: `<div class="grid grid-cols-2 gap-4" data-component="Grid"><div class="p-4 border rounded">Item 1</div><div class="p-4 border rounded">Item 2</div></div>`,
      },
      {
        id: "grid-3",
        label: "Grid (3 cols)",
        description: "Three-column grid layout",
        icon: Grid3x3,
        gradient: "from-indigo-500 to-purple-600",
        html: `<div class="grid grid-cols-3 gap-4" data-component="Grid"><div class="p-4 border rounded">Item 1</div><div class="p-4 border rounded">Item 2</div><div class="p-4 border rounded">Item 3</div></div>`,
      },
      {
        id: "section",
        label: "Section",
        description: "Page section with title",
        icon: PanelTop,
        gradient: "from-sky-400 to-sky-600",
        html: `<section class="py-8 px-6"><h2 class="text-xl font-semibold mb-4">Section Title</h2><div class="flex flex-col gap-4"><p class="text-sm text-muted-foreground">Section content</p></div></section>`,
      },
      {
        id: "divider",
        label: "Divider",
        description: "Horizontal separator",
        icon: Minus,
        gradient: "from-gray-400 to-gray-500",
        html: `<hr class="border-border my-4" />`,
      },
    ],
  },
  {
    label: "Content",
    blocks: [
      {
        id: "heading-1",
        label: "Heading 1",
        description: "Large page title",
        icon: Heading1,
        gradient: "from-orange-400 to-orange-600",
        html: `<h1 class="text-2xl font-bold tracking-tight">Heading</h1>`,
      },
      {
        id: "heading-2",
        label: "Heading 2",
        description: "Section heading",
        icon: Heading2,
        gradient: "from-orange-500 to-amber-600",
        html: `<h2 class="text-xl font-semibold tracking-tight">Heading</h2>`,
      },
      {
        id: "paragraph",
        label: "Paragraph",
        description: "Body text block",
        icon: AlignLeft,
        gradient: "from-amber-400 to-amber-600",
        html: `<p class="text-sm">Paragraph text goes here.</p>`,
      },
      {
        id: "button-primary",
        label: "Button",
        description: "Primary action button",
        icon: MousePointer,
        gradient: "from-rose-400 to-rose-600",
        html: `<button class="inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 h-10 px-4 py-2" data-action="navigate" data-action-to="/">Button</button>`,
      },
      {
        id: "image",
        label: "Image",
        description: "Image element",
        icon: Image,
        gradient: "from-teal-400 to-teal-600",
        html: `<img src="https://placehold.co/400x200" alt="Placeholder" class="rounded-md object-cover" />`,
      },
      {
        id: "badge",
        label: "Badge",
        description: "Status indicator",
        icon: Tag,
        gradient: "from-purple-400 to-purple-600",
        html: `<span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold bg-secondary text-secondary-foreground">Badge</span>`,
      },
      {
        id: "card",
        label: "Card",
        description: "Bordered content card",
        icon: CreditCard,
        gradient: "from-emerald-400 to-emerald-600",
        html: `<div class="rounded-lg border bg-card p-4" data-component="Card"><h3 class="font-semibold">Card Title</h3><p class="text-sm text-muted-foreground mt-1">Card description.</p></div>`,
      },
      {
        id: "stat-card",
        label: "Stat Card",
        description: "Metric display card",
        icon: BarChart3,
        gradient: "from-cyan-400 to-cyan-600",
        html: `<div class="rounded-lg border bg-card p-6" data-component="StatCard"><span class="text-sm text-muted-foreground">Total Users</span><div class="mt-2 text-2xl font-bold">1,234</div><span class="text-xs text-muted-foreground">+12% from last month</span></div>`,
      },
      {
        id: "empty-state",
        label: "Empty State",
        description: "No content placeholder",
        icon: AlertCircle,
        gradient: "from-gray-400 to-gray-600",
        html: `<div class="flex flex-col items-center justify-center py-12 text-center gap-3" data-component="EmptyState"><h3 class="text-lg font-medium">No items yet</h3><p class="text-sm text-muted-foreground">Get started by creating your first item.</p></div>`,
      },
    ],
  },
  {
    label: "Form Inputs",
    blocks: [
      { id: "input-text", label: "Text Box", description: "Single-line text field", icon: TextCursorInput, gradient: "from-violet-400 to-violet-600", html: "" },
      { id: "input-textarea", label: "Textarea", description: "Multi-line text area", icon: AlignJustify, gradient: "from-violet-500 to-purple-600", html: "" },
      { id: "input-password", label: "Password", description: "Masked password field", icon: Lock, gradient: "from-slate-400 to-slate-600", html: "" },
      { id: "input-email", label: "Email", description: "Email address field", icon: Mail, gradient: "from-blue-400 to-blue-600", html: "" },
      { id: "input-number", label: "Number", description: "Numeric input", icon: Hash, gradient: "from-amber-400 to-amber-600", html: "" },
      { id: "input-phone", label: "Phone", description: "Phone number field", icon: Phone, gradient: "from-green-400 to-green-600", html: "" },
      { id: "input-url", label: "URL", description: "Website URL field", icon: Link2, gradient: "from-cyan-400 to-cyan-600", html: "" },
      { id: "input-date", label: "Date Picker", description: "Date selection input", icon: Calendar, gradient: "from-rose-400 to-rose-600", html: "" },
      { id: "input-select", label: "Select", description: "Dropdown option picker", icon: ListFilter, gradient: "from-fuchsia-400 to-fuchsia-600", html: "" },
      { id: "input-checkbox", label: "Checkbox", description: "Boolean toggle", icon: CheckSquare, gradient: "from-green-400 to-green-600", html: "" },
      { id: "input-radio", label: "Radio Group", description: "Single-choice options", icon: CheckSquare, gradient: "from-indigo-400 to-indigo-600", html: "" },
      { id: "input-toggle", label: "Toggle / Switch", description: "On/off switch", icon: ToggleRight, gradient: "from-emerald-400 to-emerald-600", html: "" },
      { id: "input-range", label: "Slider", description: "Range slider", icon: SlidersHorizontal, gradient: "from-sky-400 to-sky-600", html: "" },
      { id: "input-file", label: "File Upload", description: "Drag & drop file upload", icon: Paperclip, gradient: "from-orange-400 to-orange-600", html: "" },
      { id: "input-with-icon", label: "Input with Icon", description: "Text input with leading icon", icon: Search, gradient: "from-blue-400 to-blue-600", html: "" },
      { id: "input-with-addon", label: "Input with Addon", description: "Input with prefix/suffix", icon: Type, gradient: "from-teal-400 to-teal-600", html: "" },
      { id: "form-login", label: "Login Form", description: "Email + password form", icon: FormInput, gradient: "from-blue-500 to-indigo-700", html: "" },
      { id: "form-contact", label: "Contact Form", description: "Full contact form", icon: FormInput, gradient: "from-purple-500 to-purple-700", html: "" },
    ],
  },
  {
    label: "Navigation",
    blocks: [
      { id: "navbar", label: "Navbar", description: "Top navigation bar", icon: Navigation, gradient: "from-slate-500 to-slate-700", html: "" },
      { id: "sidebar-nav", label: "Sidebar Nav", description: "Vertical sidebar menu", icon: Layers, gradient: "from-gray-500 to-gray-700", html: "" },
      { id: "breadcrumb", label: "Breadcrumb", description: "Page path indicator", icon: ChevronRight, gradient: "from-zinc-400 to-zinc-600", html: "" },
      { id: "tabs", label: "Tabs", description: "Tab switcher", icon: MoreHorizontal, gradient: "from-blue-400 to-blue-600", html: "" },
      { id: "pagination", label: "Pagination", description: "Page navigation", icon: MoreHorizontal, gradient: "from-indigo-400 to-indigo-600", html: "" },
      { id: "steps", label: "Steps / Progress", description: "Multi-step progress", icon: List, gradient: "from-violet-400 to-violet-600", html: "" },
    ],
  },
  {
    label: "Feedback",
    blocks: [
      { id: "alert-info", label: "Alert (Info)", description: "Blue info alert", icon: Info, gradient: "from-blue-400 to-blue-600", html: "" },
      { id: "alert-success", label: "Alert (Success)", description: "Green success alert", icon: CheckCircle, gradient: "from-green-400 to-green-600", html: "" },
      { id: "alert-warning", label: "Alert (Warning)", description: "Yellow warning alert", icon: AlertTriangle, gradient: "from-yellow-400 to-yellow-600", html: "" },
      { id: "alert-error", label: "Alert (Error)", description: "Red error alert", icon: XCircle, gradient: "from-red-400 to-red-600", html: "" },
      { id: "progress-bar", label: "Progress Bar", description: "Completion progress bar", icon: Activity, gradient: "from-emerald-400 to-emerald-600", html: "" },
      { id: "skeleton", label: "Skeleton Loader", description: "Loading placeholder", icon: Layers, gradient: "from-gray-300 to-gray-500", html: "" },
    ],
  },
  {
    label: "Data Components",
    blocks: [
      {
        id: "data-table",
        label: "Data Table",
        description: "Tabular data display",
        icon: Table2,
        gradient: "from-emerald-500 to-green-700",
        html: `<div class="w-full border rounded-lg" data-component="DataTable" data-source="items"><table class="w-full border-collapse"><thead><tr class="border-b"><th class="text-left p-2 text-sm font-medium text-muted-foreground">Name</th><th class="text-left p-2 text-sm font-medium text-muted-foreground">Status</th></tr></thead><tbody><tr class="border-b" data-repeat="items"><td class="p-2 text-sm" data-field="name">{{name}}</td><td class="p-2 text-sm" data-field="status">{{status}}</td></tr></tbody></table></div>`,
      },
      {
        id: "form",
        label: "Form",
        description: "Input form with submit",
        icon: FormInput,
        gradient: "from-blue-500 to-blue-700",
        html: `<form class="space-y-4 p-4 border rounded-lg" data-component="Form" data-bind="state:form" data-action="mutate" data-action-source="createItem"><div class="space-y-2"><label class="text-sm font-medium">Name</label><input type="text" class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder="Enter name" data-bind="state:form.name" /></div><button type="submit" class="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground h-10 px-4 py-2 text-sm font-medium">Submit</button></form>`,
      },
      {
        id: "repeater",
        label: "Repeater",
        description: "Loop over data items",
        icon: Repeat,
        gradient: "from-amber-500 to-amber-700",
        html: `<div class="flex flex-col gap-4" data-repeat="items" data-repeat-key="id"><div class="p-4 border rounded-lg"><h4 class="font-medium" data-field="name">{{name}}</h4><p class="text-sm text-muted-foreground" data-field="description">{{description}}</p></div></div>`,
      },
    ],
  },
  {
    label: "Slots",
    blocks: [
      {
        id: "slot-entity-table",
        label: "Entity Table Slot",
        description: "Auto-filled data table",
        icon: Table2,
        gradient: "from-purple-500 to-purple-700",
        html: `<div class="min-h-[100px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center" data-slot="entity-table" data-entity="Entity"><span class="text-sm text-muted-foreground">Entity Table Slot</span></div>`,
      },
      {
        id: "slot-entity-form",
        label: "Entity Form Slot",
        description: "Auto-filled input form",
        icon: FileInput,
        gradient: "from-indigo-500 to-indigo-700",
        html: `<div class="min-h-[100px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center" data-slot="entity-form" data-entity="Entity"><span class="text-sm text-muted-foreground">Entity Form Slot</span></div>`,
      },
      {
        id: "slot-stat-cards",
        label: "Stat Cards Slot",
        description: "Auto-filled metric cards",
        icon: Presentation,
        gradient: "from-rose-500 to-rose-700",
        html: `<div class="min-h-[100px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center" data-slot="stat-cards" data-entity="Entity"><span class="text-sm text-muted-foreground">Stat Cards Slot</span></div>`,
      },
      {
        id: "slot-crud-actions",
        label: "CRUD Actions Slot",
        description: "Create/edit/delete actions",
        icon: LayoutTemplate,
        gradient: "from-sky-500 to-sky-700",
        html: `<div class="min-h-[60px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center" data-slot="crud-actions" data-entity="Entity"><span class="text-sm text-muted-foreground">CRUD Actions Slot</span></div>`,
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ComponentPaletteProps {
  editor: Editor | null;
}

export function ComponentPalette({ editor }: ComponentPaletteProps) {
  // Track selected component so we can show where blocks will land
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const [selectedDroppable, setSelectedDroppable] = useState(false);

  useEffect(() => {
    if (!editor) return;

    const update = () => {
      const sel = editor.getSelected();
      if (sel) {
        const label =
          sel.get("tagName") ||
          sel.getClasses()?.[0] ||
          "element";
        setSelectedLabel(label);
        setSelectedDroppable(sel.get("droppable") !== false);
      } else {
        setSelectedLabel(null);
        setSelectedDroppable(false);
      }
    };

    editor.on("component:selected", update);
    editor.on("component:deselected", update);
    return () => {
      editor.off("component:selected", update);
      editor.off("component:deselected", update);
    };
  }, [editor]);

  // Resolve block HTML: prefer inline html, fall back to GrapeJS BlockManager content
  const resolveHtml = useCallback(
    (block: BlockDef): string => {
      if (block.html) return block.html;
      const gjsBlock = (editor as any)?.Blocks?.get?.(block.id);
      const content = gjsBlock?.get?.("content");
      if (typeof content === "string") return content;
      return "";
    },
    [editor],
  );

  // Click: append inside selected component (if droppable), else add to page root
  const handleClick = useCallback(
    (block: BlockDef) => {
      if (!editor) return;
      const html = resolveHtml(block);
      if (!html) return;
      const sel = editor.getSelected();
      if (sel && sel.get("droppable") !== false) {
        sel.append(html);
      } else {
        editor.addComponents(html);
      }
    },
    [editor, resolveHtml],
  );

  // Drag: use GrapeJS's own BlockManager drag so it handles the drop target
  const handleMouseDown = useCallback(
    (e: React.MouseEvent, block: BlockDef) => {
      if (!editor || e.button !== 0) return;
      // GrapeJS >= 0.21 exposes Blocks.startDrag; fall back to no-op
      const gjsBlock = (editor as any).Blocks?.get?.(block.id);
      if (gjsBlock && (editor as any).Blocks?.startDrag) {
        (editor as any).Blocks.startDrag(gjsBlock);
      }
    },
    [editor],
  );

  return (
    <div className="flex shrink-0 flex-col bg-muted/20 overflow-y-auto h-full">
      {/* Drop-target indicator */}
      <div className={`px-3 py-2 text-[11px] border-b ${selectedLabel && selectedDroppable ? "bg-blue-50 text-blue-700" : "text-muted-foreground"}`}>
        {selectedLabel && selectedDroppable ? (
          <>Clicking adds <strong>inside</strong> <code className="bg-blue-100 px-1 rounded">{selectedLabel}</code></>
        ) : selectedLabel ? (
          <><code className="bg-muted px-1 rounded">{selectedLabel}</code> is not a container — adds to page root</>
        ) : (
          <>Click a block to add · select a container first to nest inside it</>
        )}
      </div>

      {/* Categories */}
      {CATEGORIES.map((category) => (
        <div key={category.label}>
          <div className="border-b border-gray-100 px-4 py-2 bg-muted/30">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {category.label}
            </span>
          </div>

          {category.blocks.map((block) => (
            <div
              key={block.id}
              className="flex cursor-pointer items-center gap-3 px-3 py-2.5 hover:bg-muted/60 active:bg-muted/80 select-none"
              onMouseDown={(e) => handleMouseDown(e, block)}
              onClick={() => handleClick(block)}
              title={`${block.description} — click to add`}
            >
              <div
                className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${block.gradient}`}
              >
                <block.icon className="h-4 w-4 text-white" />
              </div>

              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-slate-800">
                  {block.label}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {block.description}
                </div>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
