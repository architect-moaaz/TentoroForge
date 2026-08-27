"use client";
import { useState } from "react";
import { ChevronRight, PanelLeftClose, Search, X } from "lucide-react";
import { starterRegistry } from "@forge/registry";
import * as Lucide from "lucide-react";
import { setDraggingComponent } from "@/lib/palette-drag";

interface PaletteProps {
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
}

const CATEGORY_ORDER: Array<{ id: string; label: string }> = [
  { id: "layout", label: "Layout" },
  { id: "input", label: "Input" },
  { id: "display", label: "Display" },
  { id: "interactive", label: "Interactive" },
  { id: "data", label: "Data" },
  { id: "feedback", label: "Feedback" },
  { id: "navigation", label: "Navigation" },
];

// Gradient backgrounds per category
const CATEGORY_GRADIENT: Record<string, string> = {
  layout:      "from-violet-500 to-purple-600",
  input:       "from-rose-500 to-red-600",
  display:     "from-cyan-500 to-blue-600",
  interactive: "from-amber-500 to-orange-600",
  data:        "from-emerald-500 to-green-600",
  feedback:    "from-pink-500 to-rose-600",
  navigation:  "from-indigo-500 to-blue-600",
};

// Map component name → lucide icon name
const COMPONENT_ICON: Record<string, string> = {
  Container: "Square", Grid: "Grid3x3", Card: "Layers", Divider: "Minus",
  Spacer: "Square", Stack: "AlignJustify", Row: "MoreHorizontal",
  Hero: "Image", Section: "PanelTop", Split: "Columns2",
  Sidebar: "PanelLeft", Cluster: "Group", Tabs: "PanelTop",
  Accordion: "Layers", AccordionPanel: "ChevronDown", TabPanel: "PanelTop",
  AppShell: "LayoutDashboard", InspectorPanel: "PanelRight", TabPanelWithDeepLink: "Link",
  Button: "MousePointer", IconButton: "Pointer", Link: "Link",
  Input: "TextCursor", Textarea: "AlignLeft", Select: "ChevronDown",
  Checkbox: "Check", DatePicker: "Calendar",
  Heading: "Heading", Avatar: "User", Badge: "Tag", KeyValueList: "List",
  FeatureCard: "Star", Skeleton: "Loader",
  Table: "Table2", Chart: "BarChart3", Sparkline: "Activity",
  DataGrid: "Grid3x3", Timeline: "GitBranch", TableSortable: "Table2",
  Alert: "AlertCircle", EmptyState: "Inbox", LoadingState: "Loader",
  EmptyStateRich: "Inbox", DateRangePicker: "CalendarDays", MultiSelect: "List",
  ApprovalStepper: "CheckSquare", PersonCard: "User", FilterBar: "Filter",
  CommandPalette: "Command", ActivityFeed: "Activity",
  Form: "FileText", NavLink: "Link", Breadcrumb: "ChevronRight",
  FadeIn: "Sparkles", Stagger: "Sparkles",
};

function iconFor(name: string, entryIcon?: string) {
  // Prefer the hand-tuned override, then the registry entry's own icon (103/106
  // entries define one), then a generic square. This closes the ~53-component
  // "everything is a gray square" gap without maintaining a parallel map.
  const iconName = COMPONENT_ICON[name] ?? entryIcon ?? "Square";
  return (Lucide as any)[iconName] ?? Lucide.Square;
}

const SECTION_HDR =
  "px-3 py-1.5 flex items-center justify-between text-[10px] font-semibold tracking-wide text-muted-foreground uppercase";

export function Palette({ collapsed = false, onToggleCollapsed }: PaletteProps = {}) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const matches = (e: any) =>
    !q ||
    e.name.toLowerCase().includes(q) ||
    (e.description ?? "").toLowerCase().includes(q);

  // Group registry entries by category
  const byCategory = Object.values(starterRegistry).reduce((acc, e: any) => {
    (acc[e.category] = acc[e.category] || []).push(e);
    return acc;
  }, {} as Record<string, any[]>);

  if (collapsed) {
    return (
      <aside className="w-10 border-r bg-background flex flex-col h-full">
        <button
          onClick={onToggleCollapsed}
          className="h-10 w-10 grid place-items-center hover:bg-muted text-muted-foreground hover:text-foreground border-b"
          title="Expand Components"
          aria-label="Expand components panel"
        >
          <ChevronRight size={16} />
        </button>
        <button
          onClick={onToggleCollapsed}
          className="flex-1 hover:bg-muted text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
          title="Expand components panel"
          style={{ writingMode: "vertical-rl" }}
        >
          Components
        </button>
      </aside>
    );
  }

  return (
    <aside className="w-72 border-r bg-background flex flex-col h-full">
      <header className={SECTION_HDR}>
        <span>Components</span>
        {onToggleCollapsed && (
          <button
            onClick={onToggleCollapsed}
            className="text-muted-foreground hover:text-foreground"
            title="Collapse components panel"
            aria-label="Collapse components panel"
          >
            <PanelLeftClose size={14} />
          </button>
        )}
      </header>

      <div className="px-2 pt-2 pb-1">
        <div className="relative">
          <Search
            size={13}
            className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search components…"
            aria-label="Search components"
            className="w-full rounded-md border bg-background py-1.5 pl-7 pr-7 text-xs outline-none focus:ring-2 focus:ring-ring"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      <div className="overflow-y-auto pb-4">
        {q && !CATEGORY_ORDER.some(({ id }) => (byCategory[id] ?? []).some(matches)) && (
          <p className="px-3 py-4 text-center text-xs text-muted-foreground">
            No components match “{query}”.
          </p>
        )}
        {CATEGORY_ORDER.map(({ id, label }) => {
          const entries = (byCategory[id] ?? []).filter(matches);
          if (entries.length === 0) return null;
          return (
            <div key={id} className="mb-3">
              <h4 className="px-3 py-1 text-[10px] tracking-wider uppercase text-muted-foreground">
                {label}
              </h4>
              <ul className="space-y-0.5">
                {entries.map((e: any) => {
                  const Icon = iconFor(e.name, (e as { icon?: string }).icon);
                  return (
                    <li
                      key={e.name}
                      draggable
                      onDragStart={(ev) => {
                        ev.dataTransfer.setData("text/x-forge-component", e.name);
                        ev.dataTransfer.effectAllowed = "copy";
                        setDraggingComponent(e.name);
                      }}
                      onDragEnd={() => setDraggingComponent(null)}
                      className="mx-2 px-2 py-1.5 rounded-md hover:bg-muted/50 cursor-grab flex items-start gap-2.5"
                      title={e.description ?? e.name}
                    >
                      <span
                        className={`flex-shrink-0 h-9 w-9 rounded-lg bg-gradient-to-br ${
                          CATEGORY_GRADIENT[id] ?? "from-slate-400 to-slate-600"
                        } grid place-items-center text-white shadow-sm`}
                      >
                        <Icon size={16} />
                      </span>
                      <span className="min-w-0 flex-1 pt-0.5">
                        <span className="block text-sm font-medium truncate">{e.name}</span>
                        {e.description && (
                          <span className="block text-[10.5px] text-muted-foreground truncate">
                            {e.description}
                          </span>
                        )}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
