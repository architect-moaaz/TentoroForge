/**
 * Centralised icon resolver — maps a small set of semantic keys to Lucide
 * icon components. Schemas and library components reference icons by
 * stable string keys (`"clock"`, `"check-circle"`, `"calendar"`) rather
 * than importing Lucide directly. That keeps the LLM prompt surface
 * stable (a short whitelist of known keys) and lets us swap the icon
 * library without touching every consumer.
 *
 * Adding a new icon: import it below and add a row to ICON_MAP. The key is
 * kebab-lowercase (that is the canonical spelling), but `resolveIcon` matches
 * loosely — see NAMING below — so you do not need alias rows for the
 * PascalCase spelling of the same icon.
 *
 * ENUMERATION — `ICON_NAMES`
 * --------------------------
 * ICON_MAP itself is module-private, and for years there was NO way to ask the
 * library which icon names are valid. The editor's `iconPicker` control
 * therefore fell back to a plain text field, the author typed a guess, and an
 * IconButton dropped from the palette rendered the literal WORD "Plus".
 * `ICON_NAMES` is the public, stable list the picker UI enumerates
 * (frontend/src/components/properties/PropControls). Keep the name — a
 * frontend control imports it from "@tentoroforge/library".
 *
 * NAMING — two conventions in one tree
 * ------------------------------------
 * ICON_MAP keys are kebab-lowercase (`"chevron-down"`), but the registry
 * catalog's `entry.icon` fields are Lucide PascalCase (`"ChevronDown"`,
 * "MousePointer"), and LLM-authored schemas emit either. The old resolver only
 * lowercased, so `"Plus"` resolved by luck (one word) while `"ChevronDown"`
 * became `"chevrondown"` and matched nothing. `resolveIcon` now compares a
 * CANONICAL form — lowercase, separators stripped — so `"chevron-down"`,
 * `"ChevronDown"`, `"chevron_down"` and `"chevronDown"` all land on the same
 * icon. Kebab stays canonical for storage and for ICON_NAMES.
 *
 * The entity/navigation keys are kept in sync with
 * `backend/services/shell_templates.py:_ICONS`. Rows added below that block for
 * the editor palette are a SUPERSET — the backend's keys all still resolve, so
 * nothing there needs to change.
 */
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Calendar,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronsLeft,
  ChevronsRight,
  Clock,
  Flag,
  HelpCircle,
  LayoutGrid,
  Minus,
  MoreHorizontal,
  Plus,
  Search,
  Settings,
  ShoppingCart,
  Tag,
  Truck,
  User,
  Users,
  CreditCard,
  X,
  Home,
  LayoutDashboard,
  ClipboardList,
  Inbox,
  UserCog,
  Wrench,
  Package,
  FileText,
  Receipt,
  Shield,
  CalendarCheck,
  BarChart2,
  GitBranch,
  Mail,
  Box,
  Circle,
  Building2,
  DollarSign,
  Wallet,
  PieChart,
  DoorOpen,
  Car,
  Bell,
  Folder,
  BookOpen,
  Activity,
  GraduationCap,
  UserCheck,
  TrendingUp,
  Ticket,
  Megaphone,
  CalendarClock,
  ArrowLeftRight,
  Square,
  Layers,
  Bookmark,
  Stethoscope,
  // Editor-palette icons: every `icon:` field in packages/registry/src/starter.ts
  // (the component catalog) so the palette and the icon picker can render a real
  // glyph for each entry instead of a blank.
  AlertCircle,
  AlignHorizontalJustifyStart,
  AlignJustify,
  AlignLeft,
  AppWindow,
  ArrowUpDown,
  CalendarRange,
  Camera,
  CheckSquare,
  CircleDot,
  Code,
  Coins,
  Columns,
  Columns2,
  Command,
  Compass,
  CornerUpRight,
  Database,
  ExternalLink,
  Filter,
  Focus,
  FolderTree,
  GalleryHorizontal,
  Gauge,
  Grid3x3,
  Hash,
  Heading,
  IdCard,
  Image as ImageIcon,
  ImageOff,
  Info,
  Keyboard,
  Layers3,
  Layout,
  LayoutPanelTop,
  LineChart,
  Link as LinkIcon,
  List,
  ListChecks,
  ListOrdered,
  ListPlus,
  Loader,
  LoaderCircle,
  Map as MapIcon,
  Menu,
  MessageSquare,
  MousePointer,
  MousePointer2,
  MousePointerClick,
  PackageOpen,
  Palette,
  PanelLeft,
  PanelRight,
  Pilcrow,
  QrCode,
  RefreshCw,
  Repeat,
  ScanBarcode,
  ScanLine,
  ShoppingBag,
  SkipForward,
  Sparkles,
  Star,
  SunMoon,
  Sunrise,
  Table,
  Table2,
  TextCursor,
  TextCursorInput,
  ToggleLeft,
  Trello,
  Undo2,
  UserCircle,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

const ICON_MAP: Record<string, LucideIcon> = {
  alert:              AlertTriangle,
  "alert-triangle":   AlertTriangle,
  "arrow-down":       ArrowDown,
  "arrow-up":         ArrowUp,
  calendar:           Calendar,
  check:              Check,
  "check-circle":     CheckCircle2,
  "chevron-down":     ChevronDown,
  "chevron-left":     ChevronLeft,
  "chevron-right":    ChevronRight,
  "chevron-up":       ChevronUp,
  "chevrons-left":    ChevronsLeft,
  "chevrons-right":   ChevronsRight,
  clock:              Clock,
  "credit-card":      CreditCard,
  "help-circle":      HelpCircle,
  "layout-grid":      LayoutGrid,
  "shopping-cart":    ShoppingCart,
  truck:              Truck,
  close:              X,
  flag:               Flag,
  minus:              Minus,
  more:               MoreHorizontal,
  "more-horizontal":  MoreHorizontal,
  plus:               Plus,
  search:             Search,
  settings:           Settings,
  tag:                Tag,
  user:               User,
  users:              Users,
  x:                  X,
  // Navigation / entity keys emitted by the shell's _icon_for (keep in sync with
  // backend/services/shell_templates.py:_ICONS) plus common LLM aliases.
  home:               Home,
  "layout-dashboard": LayoutDashboard,
  dashboard:          LayoutDashboard,
  "layout-kanban":    LayoutDashboard,
  board:              LayoutDashboard,
  "clipboard-list":   ClipboardList,
  inbox:              Inbox,
  "user-cog":         UserCog,
  wrench:             Wrench,
  package:            Package,
  box:                Box,
  "file-text":        FileText,
  receipt:            Receipt,
  shield:             Shield,
  "calendar-check":   CalendarCheck,
  "bar-chart-2":      BarChart2,
  "chart-bar":        BarChart2,
  report:             BarChart2,
  reports:            BarChart2,
  "git-branch":       GitBranch,
  mail:               Mail,
  circle:             Circle,
  "circle-check":     CheckCircle2,
  // Extended entity/domain keys — keep in sync with _ICONS in
  // backend/services/shell_templates.py.
  building:           Building2,
  "dollar-sign":      DollarSign,
  wallet:             Wallet,
  "pie-chart":        PieChart,
  "door-open":        DoorOpen,
  car:                Car,
  bell:               Bell,
  folder:             Folder,
  "book-open":        BookOpen,
  "heart-pulse":      Activity,
  activity:           Activity,
  "graduation-cap":   GraduationCap,
  // DIVERGENCE FOUND while auditing the sync: _ICONS maps doctor/physician/
  // provider → "stethoscope" and this map had no such row, so every clinical
  // nav item the shell generated rendered with no glyph at all. Backend
  // unchanged; the row belongs here.
  stethoscope:        Stethoscope,
  "user-check":       UserCheck,
  "trending-up":      TrendingUp,
  ticket:             Ticket,
  megaphone:          Megaphone,
  "calendar-clock":   CalendarClock,
  "arrow-left-right": ArrowLeftRight,
  "settings-2":       Settings,
  square:             Square,
  layers:             Layers,
  bookmark:           Bookmark,
  // Editor-palette keys. Every `entry.icon` in the component catalog
  // (packages/registry/src/starter.ts) has a row here, so the palette, the
  // layer tree and the icon picker all resolve rather than showing a hole.
  // Sourced from the catalog, not hand-picked: if you add a catalog entry with
  // a new Lucide icon, add it here too — `tests/icons.test.ts` fails otherwise.
  "alert-circle":                   AlertCircle,
  "align-horizontal-justify-start": AlignHorizontalJustifyStart,
  "align-justify":                  AlignJustify,
  "align-left":                     AlignLeft,
  "app-window":                     AppWindow,
  "arrow-up-down":                  ArrowUpDown,
  "calendar-range":                 CalendarRange,
  camera:                           Camera,
  "check-square":                   CheckSquare,
  "circle-dot":                     CircleDot,
  code:                             Code,
  coins:                            Coins,
  columns:                          Columns,
  "columns-2":                      Columns2,
  command:                          Command,
  compass:                          Compass,
  "corner-up-right":                CornerUpRight,
  database:                         Database,
  "external-link":                  ExternalLink,
  filter:                           Filter,
  focus:                            Focus,
  "folder-tree":                    FolderTree,
  "gallery-horizontal":             GalleryHorizontal,
  gauge:                            Gauge,
  "grid-3x3":                       Grid3x3,
  hash:                             Hash,
  heading:                          Heading,
  "id-card":                        IdCard,
  image:                            ImageIcon,
  "image-off":                      ImageOff,
  info:                             Info,
  keyboard:                         Keyboard,
  "layers-3":                       Layers3,
  layout:                           Layout,
  "layout-panel-top":               LayoutPanelTop,
  "line-chart":                     LineChart,
  link:                             LinkIcon,
  list:                             List,
  "list-checks":                    ListChecks,
  "list-ordered":                   ListOrdered,
  "list-plus":                      ListPlus,
  loader:                           Loader,
  "loader-circle":                  LoaderCircle,
  map:                              MapIcon,
  menu:                             Menu,
  "message-square":                 MessageSquare,
  "mouse-pointer":                  MousePointer,
  "mouse-pointer-2":                MousePointer2,
  "mouse-pointer-click":            MousePointerClick,
  "package-open":                   PackageOpen,
  palette:                          Palette,
  "panel-left":                     PanelLeft,
  "panel-right":                    PanelRight,
  // The catalog says "SidebarRight"; Lucide renamed that glyph to PanelRight
  // and no longer exports the old name, so the alias lives here rather than
  // rewriting catalog entries.
  "sidebar-right":                  PanelRight,
  pilcrow:                          Pilcrow,
  "qr-code":                        QrCode,
  "refresh-cw":                     RefreshCw,
  repeat:                           Repeat,
  "scan-barcode":                   ScanBarcode,
  "scan-line":                      ScanLine,
  "shopping-bag":                   ShoppingBag,
  "skip-forward":                   SkipForward,
  sparkles:                         Sparkles,
  star:                             Star,
  "sun-moon":                       SunMoon,
  sunrise:                          Sunrise,
  table:                            Table,
  "table-2":                        Table2,
  "text-cursor":                    TextCursor,
  "text-cursor-input":              TextCursorInput,
  "toggle-left":                    ToggleLeft,
  trello:                           Trello,
  "undo-2":                         Undo2,
  "user-circle":                    UserCircle,
  zap:                              Zap,
};

/**
 * The public list of icon names, kebab-lowercase and sorted. This is what the
 * editor's icon-picker control enumerates — DO NOT rename it without updating
 * `frontend/src/components/properties/PropControls`, which imports it from
 * "@tentoroforge/library".
 */
export const ICON_NAMES: readonly string[] = Object.freeze(
  Object.keys(ICON_MAP).sort(),
);

/**
 * Canonicalise an icon name for LOOKUP only: lowercase, every separator
 * dropped. "ChevronDown", "chevron-down", "chevron_down" and "Chevron Down"
 * all collapse to "chevrondown". Storage keeps the kebab spelling; this exists
 * because the catalog writes PascalCase and the schemas write kebab, and a
 * resolver that only lowercased silently returned null for half of them.
 */
function canonicalIconKey(key: string): string {
  return key.toLowerCase().replace(/[^a-z0-9]/g, "");
}

const CANONICAL_ICONS: Record<string, LucideIcon> = (() => {
  const index: Record<string, LucideIcon> = {};
  for (const key of Object.keys(ICON_MAP)) {
    const canon = canonicalIconKey(key);
    // First row wins: ICON_MAP is insertion-ordered and the earlier blocks are
    // the semantic/backend keys, which are the ones we want to stay stable.
    if (!(canon in index)) index[canon] = ICON_MAP[key]!;
  }
  return index;
})();

/** Resolve an icon key to a Lucide component. Unknown keys → null. */
export function resolveIcon(key: string | undefined | null): LucideIcon | null {
  if (!key || typeof key !== "string") return null;
  // Exact kebab hit first (the common, canonical case), then the loose match
  // that lets a PascalCase catalog name find the same icon.
  return ICON_MAP[key.toLowerCase()] ?? CANONICAL_ICONS[canonicalIconKey(key)] ?? null;
}

/**
 * Does this string look like an icon NAME (as opposed to a glyph the author
 * typed directly, e.g. "✕" or "🗑")? Used by IconButton to decide whether an
 * unresolved string is a broken icon reference worth flagging or a literal
 * character to render as-is. A name is ASCII letters with optional
 * separators/digits; anything containing a non-ASCII character is a glyph.
 */
export function looksLikeIconName(key: string): boolean {
  return /^[A-Za-z][A-Za-z0-9 _-]*$/.test(key.trim());
}

/**
 * Semantic auto-icon inference. When a label / status / category string
 * matches a known keyword, return a sensible icon. Used by MetricTile
 * (icon next to label) and Card metadata rows where the schema doesn't
 * specify an icon explicitly.
 */
const KEYWORD_ICONS: Record<string, LucideIcon> = {
  // Status / lifecycle
  active: CheckCircle2, "in progress": Clock, "in_progress": Clock,
  pending: Clock, review: Clock, "in review": Clock, "in_review": Clock,
  completed: CheckCircle2, done: CheckCircle2, success: CheckCircle2,
  overdue: AlertTriangle, critical: AlertTriangle, error: AlertTriangle, failed: AlertTriangle,
  rejected: X, cancelled: X, blocked: AlertTriangle,
  // Common entities
  task: Tag, user: User, users: Users, customer: User, team: Users,
  // Date-y
  due: Calendar, scheduled: Calendar, date: Calendar, when: Calendar,
  // Misc
  search: Search, settings: Settings, more: MoreHorizontal,
  approved: Check, declined: X,
};

export function inferIcon(text: string | undefined | null): LucideIcon | null {
  if (!text || typeof text !== "string") return null;
  const key = text.toLowerCase().trim();
  return KEYWORD_ICONS[key] ?? null;
}
