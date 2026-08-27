import {
  Rows3, Columns3, LayoutGrid, Box, Square, SquareStack, SidebarOpen,
  PanelsTopLeft, PanelTop, ListTree, ListChecks, Layers, Group,
  MousePointerClick, Link as LinkIcon, ToggleLeft, Type, Heading1, Heading2, Pilcrow,
  Image as ImageIcon, CircleUser, Tag, BarChart3, BadgeCheck,
  Calendar, Inbox, AlertTriangle, BellRing, Loader, Hash,
  TextCursorInput, AlignLeft, ChevronDownSquare, CheckSquare,
  Table as TableIcon, Repeat, FileInput,
  ChevronsUpDown, Map, Sparkles, Wand2, Code,
  // Tier 2 additions
  LineChart, Activity, GanttChart,
  Users2, ListFilter, Search, ListTodo,
  CalendarRange,
  ListChecks as MultiCheck,
  PanelLeft, PanelRight, FolderTree,
  Inbox as InboxIcon,
  type LucideIcon,
} from "lucide-react";

/**
 * Per-component palette metadata. Each entry yields a colored gradient
 * icon-tile + title + description to match the DesignEditor's reference
 * visual language. Gradient strings are Tailwind utility class fragments
 * (e.g. "from-blue-400 to-blue-600") that combine with `bg-gradient-to-br`.
 */
export interface PaletteMeta {
  icon: LucideIcon;
  description: string;
  gradient: string;
}

const FALLBACK: PaletteMeta = {
  icon: Sparkles,
  description: "Component",
  gradient: "from-slate-400 to-slate-600",
};

export const PALETTE_META: Record<string, PaletteMeta> = {
  // Layout — blue/indigo/purple range
  Stack:         { icon: Rows3,            description: "Vertical flex container",       gradient: "from-blue-400 to-blue-600" },
  Row:           { icon: Columns3,         description: "Horizontal flex container",     gradient: "from-blue-500 to-indigo-600" },
  Grid:          { icon: LayoutGrid,       description: "Responsive grid",               gradient: "from-indigo-400 to-indigo-600" },
  Container:     { icon: SquareStack,      description: "Centered max-width wrapper",    gradient: "from-indigo-500 to-purple-600" },
  Spacer:        { icon: Square,           description: "Flexible spacer",               gradient: "from-slate-400 to-slate-500" },
  Box:           { icon: Box,              description: "Generic container",             gradient: "from-slate-500 to-slate-700" },
  Hero:          { icon: PanelTop,         description: "Page-leading headline block",   gradient: "from-violet-500 to-purple-600" },
  Section:       { icon: PanelsTopLeft,    description: "Page section with header",      gradient: "from-sky-400 to-sky-600" },
  Split:         { icon: Columns3,         description: "Two-column split layout",       gradient: "from-blue-500 to-cyan-600" },
  Sidebar:       { icon: SidebarOpen,      description: "Aside + main shell",            gradient: "from-indigo-500 to-blue-700" },
  Cluster:       { icon: Group,            description: "Inline group with wrap",        gradient: "from-blue-400 to-indigo-500" },
  Tabs:          { icon: PanelsTopLeft,    description: "Tabbed panels",                 gradient: "from-purple-500 to-fuchsia-600" },
  Accordion:     { icon: Layers,           description: "Collapsible panel group",       gradient: "from-violet-400 to-violet-600" },
  AccordionPanel:{ icon: ListTree,         description: "Single accordion panel",        gradient: "from-violet-300 to-violet-500" },
  TabPanel:      { icon: ListTree,         description: "Tab content panel",             gradient: "from-purple-300 to-purple-500" },

  // Interactive
  Button:        { icon: MousePointerClick, description: "Primary action button",        gradient: "from-rose-400 to-rose-600" },
  IconButton:    { icon: ToggleLeft,        description: "Icon-only button",             gradient: "from-rose-500 to-pink-600" },
  Link:          { icon: LinkIcon,          description: "Text navigation link",         gradient: "from-blue-400 to-cyan-600" },
  NavLink:       { icon: LinkIcon,          description: "Sidebar / header nav item",    gradient: "from-cyan-400 to-cyan-600" },
  Breadcrumb:    { icon: ChevronsUpDown,    description: "Breadcrumb trail",             gradient: "from-zinc-400 to-zinc-600" },

  // Form
  Form:          { icon: FileInput,         description: "Form with workflow + fields",  gradient: "from-blue-500 to-indigo-700" },
  Input:         { icon: TextCursorInput,   description: "Single-line text input",       gradient: "from-violet-400 to-violet-600" },
  Textarea:      { icon: AlignLeft,         description: "Multi-line text input",        gradient: "from-violet-500 to-purple-600" },
  Select:        { icon: ChevronDownSquare, description: "Dropdown selection",           gradient: "from-fuchsia-400 to-fuchsia-600" },
  Checkbox:      { icon: CheckSquare,       description: "Checkbox with label",          gradient: "from-green-400 to-green-600" },
  DatePicker:    { icon: Calendar,          description: "Date input",                   gradient: "from-rose-400 to-rose-600" },

  // Static / display — warm range
  Heading:       { icon: Heading1,         description: "Headline text",                gradient: "from-orange-400 to-orange-600" },
  Text:          { icon: Type,             description: "Body text",                    gradient: "from-amber-400 to-amber-600" },
  Paragraph:     { icon: Pilcrow,          description: "Paragraph block",              gradient: "from-amber-500 to-orange-600" },
  Image:         { icon: ImageIcon,        description: "Image element",                gradient: "from-teal-400 to-teal-600" },
  Avatar:        { icon: CircleUser,       description: "User portrait or initials",    gradient: "from-pink-400 to-rose-500" },
  Badge:         { icon: Tag,              description: "Small status pill",            gradient: "from-purple-400 to-purple-600" },
  Divider:       { icon: ListTree,         description: "Horizontal separator",         gradient: "from-gray-400 to-gray-500" },
  Card:          { icon: Square,           description: "Bordered content card",        gradient: "from-emerald-400 to-emerald-600" },
  EmptyState:    { icon: Inbox,            description: "Empty / no-data placeholder",  gradient: "from-gray-400 to-gray-600" },
  LoadingState:  { icon: Loader,           description: "Loading indicator",            gradient: "from-zinc-400 to-zinc-600" },
  Pagination:    { icon: ListChecks,       description: "Page navigation controls",     gradient: "from-indigo-400 to-indigo-600" },
  MetricTile:    { icon: BarChart3,        description: "Stat card with value + delta", gradient: "from-cyan-400 to-cyan-600" },
  FeatureCard:   { icon: BadgeCheck,       description: "Icon + title + description",   gradient: "from-emerald-500 to-teal-600" },
  KeyValueList:  { icon: ListTree,         description: "Definition-list display",      gradient: "from-amber-400 to-yellow-500" },
  Skeleton:      { icon: Loader,           description: "Loading placeholder",          gradient: "from-gray-300 to-gray-500" },

  // Data
  Table:         { icon: TableIcon,        description: "Tabular data grid",            gradient: "from-emerald-500 to-green-700" },
  TableSortable: { icon: TableIcon,        description: "Sortable table",               gradient: "from-green-400 to-emerald-700" },

  // Feedback
  Alert:         { icon: AlertTriangle,    description: "Inline alert banner",          gradient: "from-yellow-400 to-orange-500" },
  ConfirmDialog: { icon: BellRing,         description: "Confirm action dialog",        gradient: "from-amber-400 to-rose-500" },

  // Motion
  FadeIn:        { icon: Sparkles,         description: "Fade-in wrapper",              gradient: "from-purple-400 to-pink-500" },
  Stagger:       { icon: Wand2,            description: "Staggered reveal wrapper",     gradient: "from-fuchsia-400 to-purple-600" },

  // Custom
  CustomBlock:   { icon: Code,             description: "Raw HTML / Tailwind block",    gradient: "from-pink-500 to-rose-700" },

  // Slot (layout-mode only)
  Slot:          { icon: Hash,             description: "Layout slot placeholder",      gradient: "from-purple-500 to-purple-700" },

  // Repeater / data-flow
  Repeat:        { icon: Repeat,           description: "Repeat children per record",   gradient: "from-amber-500 to-amber-700" },

  // Heading variants (when planner emits them as separate palette items)
  Heading1:      { icon: Heading1,         description: "Large page title",             gradient: "from-orange-400 to-orange-600" },
  Heading2:      { icon: Heading2,         description: "Section heading",              gradient: "from-orange-500 to-amber-600" },

  // Tier 2 — data visualisation
  Chart:               { icon: LineChart,   description: "Line/bar/area chart for time-series + trends",  gradient: "from-blue-500 to-cyan-600" },
  Sparkline:           { icon: Sparkles,    description: "Inline mini-chart for tables + metric trends",  gradient: "from-cyan-400 to-blue-500" },
  DataGrid:            { icon: GanttChart,  description: "Frozen-column sortable virtualised table",      gradient: "from-slate-500 to-zinc-700" },
  Timeline:            { icon: Activity,    description: "Vertical event log with status markers",        gradient: "from-emerald-500 to-teal-600" },

  // Tier 2 — Batch 2 enterprise patterns
  ApprovalStepper:     { icon: ListChecks,  description: "Multi-stage approval flow visualisation",       gradient: "from-amber-500 to-orange-600" },
  PersonCard:          { icon: Users2,      description: "Avatar + role + manager composite",             gradient: "from-pink-500 to-rose-600" },
  FilterBar:           { icon: ListFilter,  description: "URL-persisted filter chips + saved views",      gradient: "from-fuchsia-500 to-pink-600" },
  CommandPalette:      { icon: Search,      description: "Cmd-K modal with fuzzy search",                 gradient: "from-indigo-500 to-purple-700" },
  ActivityFeed:        { icon: ListTodo,    description: "Project-wide audit-trail sidebar",              gradient: "from-violet-500 to-fuchsia-600" },

  // Tier 2 — Batch 3 filter ergonomics + first-render UX
  EmptyStateRich:      { icon: InboxIcon,   description: "Illustrated empty state with primary CTA",      gradient: "from-gray-400 to-zinc-600" },
  DateRangePicker:     { icon: CalendarRange, description: "Calendar + presets for time-range filtering", gradient: "from-rose-400 to-rose-600" },
  MultiSelect:         { icon: MultiCheck,  description: "Checkbox-list dropdown for multi-value filter", gradient: "from-fuchsia-400 to-fuchsia-600" },

  // Tier 2 — Wave 4 layout primitives
  AppShell:            { icon: PanelLeft,   description: "Sidebar + topbar + main + right-rail chrome",   gradient: "from-zinc-500 to-slate-700" },
  InspectorPanel:      { icon: PanelRight,  description: "Slide-out drill-in detail view",                gradient: "from-blue-500 to-indigo-700" },
  TabPanelWithDeepLink:{ icon: FolderTree,  description: "URL-aware tabs that survive refresh",            gradient: "from-purple-500 to-violet-700" },
};

export function metaFor(name: string): PaletteMeta {
  return PALETTE_META[name] ?? FALLBACK;
}
