import { generateNodeId } from "../../state/mutations";

/**
 * Default props (and starter children where applicable) for newly-dropped
 * palette items. Without these, dragging a Button onto the canvas would
 * create `{props: {}}` which fails the v2 ButtonProps schema (label is
 * required) and surfaces as "⚠ Button: invalid props" in the canvas.
 *
 * The shape returned matches the v2 node contract: { props, children? }.
 * Children get fresh node ids via generateNodeId() at call time.
 */
export interface PaletteDefault {
  props?: Record<string, unknown>;
  children?: any[];
}

/** Build a starter v2 node for the given library type with sensible
 *  defaults so the drop is immediately valid + visually present. */
export function defaultsFor(libraryName: string): PaletteDefault {
  const builder = DEFAULTS[libraryName];
  return builder ? builder() : {};
}

const placeholder = (text: string): any => ({
  id: generateNodeId(),
  type: "Text",
  props: { content: text },
});

const heading = (content: string, level = 2): any => ({
  id: generateNodeId(),
  type: "Heading",
  props: { content, level },
});

const DEFAULTS: Record<string, () => PaletteDefault> = {
  // Layout primitives — empty children + sensible structural props
  Stack:     () => ({ props: { direction: "vertical", gap: "tokens.spacing.4" }, children: [] }),
  Row:       () => ({ props: { gap: "tokens.spacing.4", align: "center", justify: "start" }, children: [] }),
  Grid:      () => ({ props: { columns: 2, gap: "tokens.spacing.4" }, children: [] }),
  Container: () => ({ props: { maxWidth: "lg" }, children: [] }),
  Spacer:    () => ({ props: { size: "tokens.spacing.4" } }),
  Box:       () => ({ props: {}, children: [] }),

  // Schema-mode layout components
  Hero: () => ({
    props: {
      eyebrow: "EYEBROW",
      headline: "Headline goes here",
      subhead: "A short subhead describing this section",
      layout: "centered",
      ctas: [
        { label: "Primary action", action: { type: "navigate", to: "/" }, variant: "primary" },
      ],
    },
    children: [],
  }),
  Section: () => ({
    props: { variant: "plain", title: "Section title", subtitle: "Section subtitle" },
    children: [],
  }),
  Split:   () => ({
    props: { ratio: "1:1", breakpoint: "md" },
    children: [
      { id: generateNodeId(), type: "Stack", props: { direction: "vertical", gap: "tokens.spacing.4" }, children: [placeholder("Left pane")] },
      { id: generateNodeId(), type: "Stack", props: { direction: "vertical", gap: "tokens.spacing.4" }, children: [placeholder("Right pane")] },
    ],
  }),
  Sidebar: () => ({
    props: { width: "240px" },
    children: [
      { id: generateNodeId(), type: "Stack", props: { direction: "vertical", gap: "tokens.spacing.2" }, children: [placeholder("Sidebar")] },
      { id: generateNodeId(), type: "Stack", props: { direction: "vertical", gap: "tokens.spacing.4" }, children: [placeholder("Main")] },
    ],
  }),
  Cluster: () => ({ props: {}, children: [] }),
  Tabs: () => {
    // Tabs requires children.length === tabs[].length, so seed both.
    const t1 = "tab-1";
    const t2 = "tab-2";
    return {
      props: { tabs: [{ id: t1, label: "Tab 1" }, { id: t2, label: "Tab 2" }], value: t1 },
      children: [
        { id: generateNodeId(), type: "Stack", props: { direction: "vertical", gap: "tokens.spacing.4" }, children: [placeholder("Tab 1 content")] },
        { id: generateNodeId(), type: "Stack", props: { direction: "vertical", gap: "tokens.spacing.4" }, children: [placeholder("Tab 2 content")] },
      ],
    };
  },
  Accordion: () => ({
    props: { mode: "single", defaultOpen: ["panel-1"] },
    children: [
      {
        id: generateNodeId(), type: "AccordionPanel",
        props: { value: "panel-1", label: "Panel 1" },
        children: [placeholder("Panel content")],
      },
    ],
  }),
  AccordionPanel: () => ({
    props: { value: "panel-1", label: "Panel" },
    children: [placeholder("Panel content")],
  }),
  TabPanel: () => ({
    props: { value: "tab-1", label: "Tab" },
    children: [placeholder("Tab content")],
  }),

  // Interactive
  Button:     () => ({ props: { label: "Button", variant: "primary", size: "md", navigate: "/" } }),
  IconButton: () => ({ props: { icon: "plus", "aria-label": "Action", variant: "primary", size: "md" } }),
  Link:       () => ({ props: { label: "Link", navigate: "/" } }),
  NavLink:    () => ({ props: { label: "Nav item", navigate: "/" } }),
  Breadcrumb: () => ({ props: { items: [{ label: "Home", href: "/" }, { label: "Current" }] } }),

  // Form
  Form: () => ({
    props: {
      workflow: "submitForm",
      fields: [{ kind: "text", name: "field", label: "Field" }],
      submitLabel: "Submit",
    },
  }),
  Input:      () => ({ props: { name: "field", label: "Field", type: "text", placeholder: "Enter a value" } }),
  Textarea:   () => ({ props: { name: "field", label: "Field", rows: 4, placeholder: "Enter text" } }),
  Select:     () => ({ props: {
    name: "field", label: "Field",
    options: [{ value: "a", label: "Option A" }, { value: "b", label: "Option B" }],
  } }),
  Checkbox:   () => ({ props: { name: "field", label: "I agree" } }),
  DatePicker: () => ({ props: { name: "date", label: "Date" } }),

  // Static / display
  Heading:      () => ({ props: { content: "Heading", level: 2 } }),
  Text:         () => ({ props: { content: "Body text" } }),
  Image:        () => ({ props: { src: "https://placehold.co/400x200", alt: "Image" } }),
  Avatar:       () => ({ props: { name: "User", size: "md" } }),
  Badge:        () => ({ props: { content: "Badge", variant: "neutral" } }),
  Divider:      () => ({ props: {} }),
  Card:         () => ({ props: {}, children: [placeholder("Card content")] }),
  EmptyState:   () => ({ props: { message: "No items yet" } }),
  LoadingState: () => ({ props: {} }),
  Pagination:   () => ({ props: { totalPages: 1, currentPage: 1 } }),
  MetricTile:   () => ({ props: { label: "Metric", value: 0, format: "number" } }),
  FeatureCard:  () => ({ props: { title: "Feature", description: "Short feature description", layout: "icon-top", icon: "star" } }),
  KeyValueList: () => ({ props: { items: [{ label: "Label", value: "Value" }, { label: "Label", value: "Value" }] } }),
  Skeleton:     () => ({ props: { variant: "rect" } }),

  // Data
  Table:         () => ({ props: { columns: [{ key: "name", label: "Name" }, { key: "value", label: "Value" }] } }),
  TableSortable: () => ({ props: { columns: [{ key: "name", label: "Name" }, { key: "value", label: "Value" }] } }),

  // Feedback
  Alert:         () => ({ props: { variant: "info", title: "Alert", description: "Alert description" } }),
  ConfirmDialog: () => ({ props: { title: "Confirm action", message: "Are you sure?", workflow: "confirm" } }),

  // Motion
  FadeIn:  () => ({ props: {}, children: [heading("Fades in")] }),
  Stagger: () => ({ props: { interval: 80 }, children: [
    heading("Item one"), heading("Item two"), heading("Item three"),
  ] }),

  // Custom
  CustomBlock: () => ({
    props: {
      html: '<p class="text-sm text-muted-foreground">Custom HTML block</p>',
      tailwind: "p-4 border rounded-md",
      label: "Custom",
    },
  }),

  // Layout-mode-only Slot
  Slot: () => ({ props: { name: "main" } }),

  // Repeat
  Repeat: () => ({
    bind: "items",
    props: {},
    children: [placeholder("{{item.name}}")],
  } as any),

  // Tier 2 — data visualisation
  Chart: () => ({
    props: {
      chartType: "line",
      data: [{ x: "Jan", y: 100 }, { x: "Feb", y: 150 }, { x: "Mar", y: 130 }, { x: "Apr", y: 200 }],
      xKey: "x",
      series: [{ name: "Series A", dataKey: "y" }],
      height: 240,
    },
  }),
  Sparkline: () => ({ props: { data: [4, 7, 5, 8, 6, 9, 7] } }),
  DataGrid: () => ({
    props: {
      columns: [
        { key: "name", label: "Name", sortable: true, frozen: true },
        { key: "status", label: "Status" },
      ],
      rows: [
        { id: "1", name: "Sample row 1", status: "Active" },
        { id: "2", name: "Sample row 2", status: "Pending" },
      ],
      rowKey: "id",
      selectable: true,
    },
  }),
  Timeline: () => ({
    props: {
      entries: [
        { id: "1", timestamp: new Date().toISOString(), title: "Event 1", actor: "User", status: "info" },
        { id: "2", timestamp: new Date().toISOString(), title: "Event 2", actor: "User", status: "approved" },
      ],
      orientation: "vertical",
    },
  }),

  // Tier 2 — Batch 2 enterprise patterns
  ApprovalStepper: () => ({
    props: {
      steps: [
        { id: "1", label: "Submitted", status: "approved" },
        { id: "2", label: "Manager Review", status: "current" },
        { id: "3", label: "Final", status: "pending" },
      ],
      orientation: "horizontal",
    },
  }),
  PersonCard: () => ({
    props: {
      name: "Sample Person",
      role: "Senior Engineer",
      status: "active",
      layout: "compact",
    },
  }),
  FilterBar: () => ({
    props: {
      showSearch: true,
      chips: [
        {
          key: "status",
          label: "Status",
          options: [
            { value: "active", label: "Active" },
            { value: "pending", label: "Pending" },
          ],
        },
      ],
    },
  }),
  CommandPalette: () => ({
    props: {
      items: [
        { id: "1", label: "Sample Action", group: "Actions", action: { type: "navigate", to: "/" } },
      ],
      placeholder: "Type to search…",
      triggerKey: "k",
    },
  }),
  ActivityFeed: () => ({
    props: {
      entries: [
        {
          id: "1",
          timestamp: new Date().toISOString(),
          actor: { name: "Sample User" },
          action: "created",
          target: "Sample Item",
          category: "create",
        },
      ],
      title: "Activity",
    },
  }),

  // Tier 2 — Batch 3 filter ergonomics + first-render UX
  EmptyStateRich: () => ({
    props: {
      icon: "inbox",
      heading: "No items yet",
      body: "Create your first item to see it here.",
      primaryCta: { label: "Create", action: { type: "navigate", to: "/new" } },
    },
  }),
  DateRangePicker: () => ({
    props: {
      name: "dateRange",
      label: "Date range",
    },
  }),
  MultiSelect: () => ({
    props: {
      name: "multiSel",
      label: "Filter",
      placeholder: "All",
      options: [
        { value: "a", label: "Option A" },
        { value: "b", label: "Option B" },
      ],
    },
  }),

  // Tier 2 — Wave 4 layout primitives
  AppShell: () => ({ props: {}, children: [] }),
  InspectorPanel: () => ({
    props: {
      paramKey: "inspector",
      title: "Detail",
      width: "default",
    },
    children: [],
  }),
  TabPanelWithDeepLink: () => ({
    props: {
      paramKey: "tab",
      tabs: [
        { id: "tab1", label: "Tab 1" },
        { id: "tab2", label: "Tab 2" },
      ],
      defaultTab: "tab1",
    },
    children: [
      { id: generateNodeId(), type: "Stack", props: { direction: "vertical", gap: "tokens.spacing.4" }, children: [placeholder("Tab 1 content")] },
      { id: generateNodeId(), type: "Stack", props: { direction: "vertical", gap: "tokens.spacing.4" }, children: [placeholder("Tab 2 content")] },
    ],
  }),
};
