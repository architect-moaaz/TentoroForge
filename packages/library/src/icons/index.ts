/**
 * Centralised icon resolver — maps a small set of semantic keys to Lucide
 * icon components. Schemas and library components reference icons by
 * stable string keys (`"clock"`, `"check-circle"`, `"calendar"`) rather
 * than importing Lucide directly. That keeps the LLM prompt surface
 * stable (a short whitelist of known keys) and lets us swap the icon
 * library without touching every consumer.
 *
 * Adding a new icon: import it below and add a row to ICON_MAP.
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
};

/** Resolve an icon key to a Lucide component. Unknown keys → null. */
export function resolveIcon(key: string | undefined | null): LucideIcon | null {
  if (!key || typeof key !== "string") return null;
  return ICON_MAP[key.toLowerCase()] ?? null;
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
