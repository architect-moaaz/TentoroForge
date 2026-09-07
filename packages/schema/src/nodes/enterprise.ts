import { z } from "zod";
import { NodeV2Ref } from "../node-ref";

const StepperStep = z.object({
  id: z.string().optional(),
  label: z.string(),
  status: z.enum(["pending", "current", "approved", "rejected", "skipped"]),
  actor: z.string().optional(),
  timestamp: z.string().optional(),  // ISO 8601
});

export const ApprovalStepperNode = z.object({
  id: z.string().optional(),
  type: z.literal("ApprovalStepper"),
  props: z.object({
    steps: z.array(StepperStep).min(1),
    orientation: z.enum(["horizontal", "vertical"]).optional(),  // default horizontal
    onStepClick: z.string().optional(),  // workflow ID to trigger on click; usually omitted
  }),
});

// Generic process stepper (non-approval semantics: pending/active/complete/error/skipped).
const GenericStepperStep = z.object({
  id: z.string().optional(),
  label: z.string(),
  description: z.string().optional(),
  status: z.enum(["pending", "active", "current", "complete", "done", "error", "skipped"]).optional(),
});
export const StepperNode = z.object({
  id: z.string().optional(),
  type: z.literal("Stepper"),
  props: z.object({
    steps: z.array(GenericStepperStep).min(1),
    orientation: z.enum(["horizontal", "vertical"]).optional(),
    activeStep: z.number().optional(),
    bind: z.string().optional(),
  }),
});

export const PersonCardNode = z.object({
  id: z.string().optional(),
  type: z.literal("PersonCard"),
  props: z.object({
    name: z.string().min(1),
    role: z.string().optional(),
    department: z.string().optional(),
    avatarUrl: z.string().optional(),
    avatarInitials: z.string().optional(),  // fallback if no avatarUrl
    email: z.string().optional(),
    // Mustache-tolerant: LLM commonly binds status to `{{item.status}}`.
    status: z.union([
      z.enum(["active", "away", "on-leave", "offline"]),
      z.string().min(1),
    ]).optional(),
    // `manager` accepts both the structured object form and a bare name
    // string (`manager: "Jane Doe"`); LLM-emitted schemas use both.
    manager: z.union([
      z.object({
        name: z.string(),
        role: z.string().optional(),
      }),
      z.string().min(1),
    ]).optional(),
    layout: z.enum(["compact", "expanded"]).optional(),  // default compact
  }),
});

const ActivityEntry = z.object({
  id: z.string().optional(),
  timestamp: z.string(),  // ISO 8601
  actor: z.object({
    name: z.string(),
    avatarInitials: z.string().optional(),
    avatarUrl: z.string().optional(),
  }),
  action: z.string(),     // e.g. "approved", "submitted", "commented on"
  target: z.string(),     // e.g. "Q1 Vacation Request" (the thing acted on)
  detail: z.string().optional(),  // one-line additional context
  category: z.enum(["create", "update", "approve", "reject", "comment", "system"]).optional(),
});

export const ActivityFeedNode = z.object({
  id: z.string().optional(),
  type: z.literal("ActivityFeed"),
  props: z.object({
    // Either an inline array of entries OR a Mustache binding string
    // like `"{{stats.latestReviews}}"` that the runtime resolves to a
    // real array. Same pattern as Form-C and Chart.data.
    // Optional with default [] so minimal { type: "ActivityFeed" } nodes render.
    entries: z.union([z.array(ActivityEntry), z.string().min(1)]).optional().default([]),
    title: z.string().optional(),
    showFilter: z.boolean().optional(),
    /** Max rows to render. Written by the dashboard composer when this
     *  sits in a grid row beside other widgets: a row is as tall as its
     *  tallest child, so an unbounded list strands the space next to it. */
    limit: z.number().int().positive().optional(),
    /** Map of contract slot -> real entity column, derived by the
     *  dashboard composer from the bound entity. Without it a feed on
     *  an entity that does not use the contract's field names renders
     *  the "Someone" placeholder on every row. */
    fields: z.record(z.string()).optional(),
    maxHeight: z.union([z.number(), z.string()]).optional(),  // px — number or CSS string (e.g. "400px")
    className: z.string().optional(),
    style: z.record(z.unknown()).optional(),
  }),
});

const FilterChip = z.object({
  key: z.string(),       // URL param key
  label: z.string(),     // Visible label
  options: z.array(z.object({
    value: z.string(),
    label: z.string(),
  })).min(1),
  defaultValue: z.string().optional(),
});

const SavedView = z.object({
  id: z.string().optional(),
  label: z.string(),
  filters: z.record(z.string()),  // key → value
});

export const FilterBarNode = z.object({
  id: z.string().optional(),
  type: z.literal("FilterBar"),
  props: z.object({
    // Data binding. The editor exposes a `bind` control for this node, and
    // without the slot here `validateProps` strips the value before the
    // component ever sees it — the control would write into a void.
    bind: z.string().optional(),
    chips: z.array(FilterChip).min(1),
    savedViews: z.array(SavedView).optional(),
    showSearch: z.boolean().optional(),
  }),
});

const CommandItem = z.object({
  id: z.string().optional(),
  label: z.string(),
  group: z.string().optional(),       // for grouping (Pages / Actions / Records)
  shortcut: z.string().optional(),    // visible hint, e.g. "⌘N"
  action: z.discriminatedUnion("type", [
    z.object({ type: z.literal("navigate"), to: z.string() }),
    z.object({ type: z.literal("workflow"), workflow: z.string() }),
  ]),
});

export const CommandPaletteNode = z.object({
  id: z.string().optional(),
  type: z.literal("CommandPalette"),
  props: z.object({
    items: z.array(CommandItem).min(1),
    placeholder: z.string().optional(),
    triggerKey: z.string().optional(),  // default "k" (i.e. Cmd+K / Ctrl+K)
  }),
});

export const EmptyStateRichNode = z.object({
  id: z.string().optional(),
  type: z.literal("EmptyStateRich"),
  props: z.object({
    icon: z.string().optional(),         // Lucide icon name (placeholder until Tier 3 illustrations)
    // Illustration: either a bare URL string (legacy: rendered directly as <img src>)
    // or a structured slot { slug, alt?, tone? } resolved via IllustrationResolver
    // to <basePath>/<slug>.svg. The structured form is preferred for Task 12+;
    // the string form is kept for backwards compat with already-generated schemas.
    illustration: z.union([
      z.string().min(1),
      z.object({
        slug: z.string().min(1),
        alt: z.string().optional(),
        tone: z.enum(["primary", "secondary", "muted"]).optional(),
      }),
    ]).optional(),
    heading: z.string().default("No data"),
    body: z.string().optional(),
    primaryCta: z.object({
      label: z.string().optional(),
      action: z.discriminatedUnion("type", [
        z.object({ type: z.literal("navigate"), to: z.string().optional() }),
        z.object({ type: z.literal("workflow"), workflow: z.string().optional() }),
      ]).optional(),
    }).optional(),
    // Accept either a bare URL string (the natural "a link" form the agent emits)
    // or a structured { label, action } CTA. Object-only rejected the common string
    // form and surfaced "⚠ EmptyStateRich: invalid props".
    sampleDataLink: z.union([
      z.string().min(1),
      z.object({
        label: z.string().optional(),
        href: z.string().optional(),
        action: z.object({ type: z.literal("workflow"), workflow: z.string().optional() }).optional(),
      }),
    ]).optional(),
    className: z.string().optional(),
    style: z.record(z.unknown()).optional(),
  }),
});

export const DateRangePickerNode = z.object({
  id: z.string().optional(),
  type: z.literal("DateRangePicker"),
  props: z.object({
    // Data binding. The editor exposes a `bind` control for this node, and
    // without the slot here `validateProps` strips the value before the
    // component ever sees it — the control would write into a void.
    bind: z.string().optional(),
    name: z.string(),                    // form field name; URL key when standalone
    label: z.string().optional(),
    startDate: z.string().optional(),    // ISO date YYYY-MM-DD
    endDate: z.string().optional(),
    presets: z.array(z.enum([
      "today", "yesterday", "last-7-days", "last-30-days",
      "quarter-to-date", "year-to-date", "custom",
    ])).optional(),
    minDate: z.string().optional(),
    maxDate: z.string().optional(),
  }),
});

export const MultiSelectNode = z.object({
  id: z.string().optional(),
  type: z.literal("MultiSelect"),
  props: z.object({
    // Data binding. The editor exposes a `bind` control for this node, and
    // without the slot here `validateProps` strips the value before the
    // component ever sees it — the control would write into a void.
    bind: z.string().optional(),
    name: z.string(),                    // URL key / form field
    label: z.string().optional(),
    placeholder: z.string().optional(),
    options: z.array(z.object({
      value: z.string(),
      label: z.string(),
    })).min(1),
    // Dynamic-options binding — build options from a page dataSource at render
    // time (relational FK multiselect, e.g. Task→Tags). Mirrors Select.optionsFrom.
    optionsFrom: z.object({
      source: z.string().min(1),
      value:  z.string().min(1).default("id"),
      label:  z.string().min(1).default("name"),
    }).optional(),
    selected: z.array(z.string()).optional(),  // initial value
    showSearch: z.boolean().optional(),  // auto when options.length > 8
    maxSelectionLabel: z.number().optional(),  // show "N selected" instead of chips when count > this
  }),
});

// Tier 2 Wave 4 — Layout Primitives

export const AppShellNode: any = z.object({
  id: z.string().optional(),
  type: z.literal("AppShell"),
  props: z.object({
    sidebar: NodeV2Ref.optional(),       // schema sub-tree for the nav
    topbar: NodeV2Ref.optional(),        // schema sub-tree for breadcrumb + user menu
    actions: NodeV2Ref.optional(),       // schema sub-tree for page actions toolbar
    rightRail: NodeV2Ref.optional(),     // schema sub-tree for context sidebar
    // Viewport below which the nav rail and right rail collapse away. Was
    // hard-coded at 768px / 1024px inside AppShell.tsx, so the three-column
    // app a user arranged became a single column on every tablet with no way
    // to say otherwise. "none" keeps every rail visible at all widths.
    breakpoint: z.enum(["sm", "md", "lg", "none"]).optional(),
  }),
  children: z.array(NodeV2Ref).default([]),  // main page content
});

export const InspectorPanelNode: any = z.object({
  id: z.string().optional(),
  type: z.literal("InspectorPanel"),
  props: z.object({
    paramKey: z.string().default("inspector"),  // URL key for active selection
    title: z.string().optional(),
    width: z.enum(["narrow", "default", "wide"]).optional(),  // 320 / 480 / 640
    // Renders the panel with no selection so it can be composed in the editor,
    // which never puts `?inspector=` on the preview URL. Without it the node
    // returns null and silently swallows everything dropped inside it.
    defaultOpen: z.boolean().optional(),
  }),
  children: z.array(NodeV2Ref).default([]),
});

const TabSpec = z.object({
  id: z.string().optional(),
  label: z.string(),
});

export const TabPanelWithDeepLinkNode: any = z.object({
  id: z.string().optional(),
  type: z.literal("TabPanelWithDeepLink"),
  props: z.object({
    paramKey: z.string().default("tab"),
    // No longer `.min(1)`: the component derives one tab per child, so an
    // empty (or absent) array is the normal state for a node built by
    // dragging panels in. Declared entries still override the derived id/label.
    tabs: z.array(TabSpec).default([]),
    defaultTab: z.string().optional(),
  }),
  children: z.array(NodeV2Ref).default([]),  // one child per tab, in order
});
