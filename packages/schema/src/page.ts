import { z } from "zod";
import { Node } from "./nodes";
import { TokenRef } from "./tokens";
import { StyleSlot } from "./style-slot";

// === v2 node type imports ===
import { CustomNode } from "./nodes/custom";
import { HeroNode, SectionNode, MetricTileNode, FeatureCardNode, CardNode, HeadingNode } from "./nodes/foundation";
import {
  SplitNode, SidebarNode, ClusterNode,
  TabsNode, AccordionNode, AccordionPanelNode,
} from "./nodes/layout-v2";
import { AvatarNode, KeyValueListNode, SkeletonNode, TagNode, StatNode, DescriptionListNode, ListNode, SegmentedControlNode, TreeNode, TransferNode, CascaderNode } from "./nodes/display";

// TabsNode and SkeletonNode in their source files apply `.refine()` to enforce
// cross-field invariants (Tabs.children.length === Tabs.props.tabs.length;
// Skeleton.lines requires variant: "text"). `.refine()` wraps the underlying
// ZodObject in a ZodEffects, which is incompatible with z.discriminatedUnion
// (which requires plain ZodObject members keyed by a literal discriminator).
//
// To preserve the O(1)-per-node parse performance of a discriminated union we
// rebuild plain (non-refined) clones of those two node types here, place the
// clones in the union, and re-apply the refines as a single `superRefine` on
// the resulting union schema (`NodeV2Refined`, below). This keeps validation
// strictness identical to the previous z.union form while eliminating the
// exponential parse cost on deep schemas.
const _TabDef = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
  icon: z.string().optional(),
}).strict();

const TabsNodePlain = z.object({
  id: z.string().min(1),
  type: z.literal("Tabs"),
  props: z.object({
    tabs:  z.array(_TabDef).min(1),
    value: z.string().min(1),
  }).strict(),
  style: StyleSlot.optional(),
  children: z.lazy(() => z.array(NodeV2Ref)),
}).strict();

const SkeletonNodePlain = z.object({
  id: z.string().min(1),
  type: z.literal("Skeleton"),
  props: z.object({
    variant: z.enum(["rect", "circle", "text"]),
    lines:   z.number().int().positive().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
// Quiet "unused import" lint — these are kept exported for downstream callers
// that import the refined versions directly.
void TabsNode; void SkeletonNode;
import { InputNode, SelectNode, TextareaNode, CheckboxNode, DatePickerNode, SwitchNode, NumberInputNode, RadioGroupNode, SliderNode, FileUploadNode, ComboboxNode, TimePickerNode, ColorPickerNode, InputOTPNode, RatingNode, MaskedInputNode, KeyValueInputNode } from "./nodes/inputs";
import { DropdownMenuNode, PopoverNode, TooltipNode, DrawerNode, ContextMenuNode, HoverCardNode, MenubarNode } from "./nodes/overlay";
import { ProgressNode, SpinnerNode, BannerNode } from "./nodes/feedback";
import { CalendarNode, KanbanNode, ResourceTimelineNode, RichTextEditorNode, CarouselNode, LightboxNode, CodeBlockNode, QRCodeNode } from "./nodes/composite";
import { BarcodeScannerNode, CameraCaptureNode, ScannerNode, ValidationChecklistNode } from "./nodes/device";
import { FadeInNode, StaggerNode } from "./nodes/motion";
import { ChartNode, SparklineNode, GaugeNode, HeatmapNode, SchematicNode } from "./nodes/charts";
import { DataGridNode, TimelineNode } from "./nodes/data-display";
import {
  ApprovalStepperNode, StepperNode, PersonCardNode, FilterBarNode,
  CommandPaletteNode, ActivityFeedNode,
  EmptyStateRichNode, DateRangePickerNode, MultiSelectNode,
  AppShellNode, InspectorPanelNode, TabPanelWithDeepLinkNode,
} from "./nodes/enterprise";

// === Shared helpers ===
import { TokenRef as TR, StyleProps } from "./tokens";
import { Expression, EventHandler, EventName, DataBinding } from "./expressions";

// === NodeV2 forward-reference machinery ===
// node-ref.ts is the shared sink that breaks the circular dependency between
// page.ts and the node files (foundation, layout-v2, motion). Node files
// import NodeV2Ref from there; page.ts calls setNodeV2Ref() to wire it up.
import { setNodeV2Ref, NodeV2Ref } from "./node-ref";
export { NodeV2Ref } from "./node-ref";

export const SCHEMA_VERSION_LITERAL = z.literal("1");

export const DataSource = z
  .object({
    name: z.string().min(1),
    entity: z.string().min(1).optional(),
    op: z.enum(["list", "get", "create", "update", "delete", "aggregate", "series", "search"]).optional(),
    metrics: z
      .record(
        z.object({
          fn: z.enum(["count", "sum", "avg", "min", "max"]),
          field: z.string().optional(),
          entity: z.string().optional(),
          window: z.enum(["today", "week", "month"]).optional(),
          dateField: z.string().optional(),
          filter: z.record(z.unknown()).optional(),
        })
      )
      .optional(),
    // op:"series" — a grouped aggregate that resolves to an array of
    // { label, value } rows for charts (category grouping, or time bucketing
    // when groupBy is a date column + bucket). See resolveSeries in the runtime.
    groupBy: z.string().optional(),
    bucket: z.enum(["day", "week", "month"]).optional(),
    agg: z
      .object({
        // `running_sum` (Slice-3 ledger) is a stateful aggregate: the resolver
        // computes cumulative SUM(field) OVER (ORDER BY <orderBy or createdAt>)
        // and returns one row per source row so the client can render a
        // running-balance column (see resolveSeries in data-engine.ts). Every
        // other fn is a plain GROUP-BY aggregate.
        fn: z.enum(["count", "sum", "avg", "min", "max", "running_sum"]),
        field: z.string().optional(),
      })
      .optional(),
    // Slice-3 ledger: when agg.fn == "running_sum", the resolver orders by
    // this column ASC (default: `createdAt`) — every ledger has one and
    // running balance is only meaningful ordered by insertion time.
    orderByCol: z.string().optional(),
    sort: z.enum(["label", "value"]).optional(),
    // SEARCH-2 op:"search" — full-text search across one or more entities'
    // `_search` tsvector columns (emitted by schema_builder for any column
    // flagged `search: true`). Resolver reads the searchable-columns
    // manifest to know which `_search` columns each entity carries.
    //   entities  — one or more entity names to search across (multi-entity
    //               search is first-class; results are ts_rank-merged).
    //   q         — the raw user query; plainto_tsquery escapes it.
    //   columns   — optional restriction to specific searchable columns
    //               (defaults to every `_search` column on the entity).
    //   snippet   — when true (default), ts_headline emits the matched
    //               snippet with `<b>…</b>` highlights around hits.
    entities: z.array(z.string().min(1)).optional(),
    q: z.string().optional(),
    columns: z.array(z.string().min(1)).optional(),
    snippet: z.boolean().optional(),
    filter: z.record(z.unknown()).optional(),
    select: z.array(z.string()).optional(),
    orderBy: z
      .array(z.object({ field: z.string(), dir: z.enum(["asc", "desc"]) }))
      .optional(),
    limit: z.number().int().positive().optional(),
    query: z.record(z.unknown()).optional(),
  });
export type DataSource = z.infer<typeof DataSource>;

export const TokenOverrides = z.record(z.record(TokenRef)).optional();

// ============================================================================
// PageV1: the original Page schema, frozen verbatim
// ============================================================================
export const PageV1 = z
  .object({
    schemaVersion: SCHEMA_VERSION_LITERAL,
    id: z.string().min(1),
    route: z.string().min(1),
    meta: z
      .object({
        title: z.string().optional(),
        description: z.string().optional(),
      })
      .strict()
      .optional(),
    layout: z.string().optional(),
    tokens: TokenOverrides,
    dataSources: z.array(DataSource).optional(),
    slots: z.record(Node).optional(),
    root: Node,
  })
  .strict();

export type PageV1T = z.infer<typeof PageV1>;

// ============================================================================
// NodeV2: union of v2 node types + structural v1 compat nodes
//
// Strategy:
// - All new v2 node types (Custom, Hero, Section, etc.) are matched first.
// - Structural v1 layout nodes (Stack, Row, Grid, etc.) are re-declared inline
//   with `children: z.array(NodeV2Ref)` so that child nodes are also validated
//   against the v2 union. This allows v2 pages like `Stack > Hero`.
// - The open-ended v1 LibraryNode is intentionally excluded: v2 pages should use
//   explicit v2 types. Unknown strings (e.g. "TotallyMadeUp") are rejected.
// - Non-layout v1 primitives (Box, Text, Image) and data nodes (Repeat,
//   Conditional, DataBoundary) are also re-declared with NodeV2Ref children.
// ============================================================================

// Shared envelope fields for structural v1-compat nodes.
// `id` is optional: LLM-generated schemas only emit ids on a few well-known
// nodes (Hero, MetricTile, root containers), but most nested nodes (Stack,
// Row, Text, Avatar within a Repeat'd Card) come without one. The runtime
// renderer falls back to array index for React keys when id is absent and
// the editor only needs ids for top-level selection. Requiring id here was
// rejecting schemas the runtime can render fine.
const V2Envelope = {
  id: z.string().min(1).optional(),
  style: StyleProps.optional().or(StyleSlot.optional()).optional(),
  // `bind` accepts either the structured DataBinding object form or a bare
  // source string (`bind: "requests"`), since the LLM emits both. Repeat
  // and a few other data-aware nodes consume it as a string at runtime.
  bind: z.union([DataBinding, z.string().min(1)]).optional(),
  visibleIf: Expression.optional(),
  on: z.record(EventName, EventHandler).optional(),
};

// ── v1-compat layout nodes with NodeV2Ref children ──
const V2StackNode = z.object({
  ...V2Envelope,
  type: z.literal("Stack"),
  props: z
    .object({
      direction: z.enum(["vertical", "horizontal"]).default("vertical"),
      gap: TR.optional(),
      align: z.enum(["start", "center", "end", "stretch"]).default("stretch"),
      justify: z.enum(["start", "center", "end", "between", "around"]).default("start"),
      wrap: z.boolean().optional(),
    })
    .strict()
    .optional(),
  children: z.array(NodeV2Ref).default([]),
});

const V2RowNode = z.object({
  ...V2Envelope,
  type: z.literal("Row"),
  props: z
    .object({
      gap: TR.optional(),
      align: z.enum(["start", "center", "end", "stretch"]).default("center"),
      justify: z.enum(["start", "center", "end", "between", "around"]).default("start"),
      wrap: z.boolean().optional(),
    })
    .strict()
    .optional(),
  children: z.array(NodeV2Ref).default([]),
});

const V2GridNode = z.object({
  ...V2Envelope,
  type: z.literal("Grid"),
  props: z
    .object({
      columns: z.number().int().min(1).max(12),
      gap: TR.optional(),
      // See nodes/layout.ts GridNode — equalRows/equalCols codify the v4
      // spike CSS fix as optional boolean schema props. Mirrored here on the
      // V2GridNode so v2 schemas (the LLM emits these) can declare the same
      // intent the v1 path supports.
      equalRows: z.boolean().optional(),
      equalCols: z.boolean().optional(),
    })
    .strict(),
  children: z.array(NodeV2Ref).default([]),
});

const V2ContainerNode = z.object({
  ...V2Envelope,
  type: z.literal("Container"),
  props: z
    .object({
      maxWidth: z.enum(["sm", "md", "lg", "xl", "2xl", "full"]).default("lg"),
    })
    .strict()
    .optional(),
  children: z.array(NodeV2Ref).default([]),
});

const V2SpacerNode = z.object({
  ...V2Envelope,
  type: z.literal("Spacer"),
  props: z.object({ size: TR }).strict(),
});

const V2BoxNode = z.object({
  ...V2Envelope,
  type: z.literal("Box"),
  props: z
    .object({
      as: z.enum(["div", "section", "article", "aside", "header", "footer", "main", "nav"])
        .default("div"),
    })
    .strict()
    .optional(),
  children: z.array(NodeV2Ref).default([]),
});

const V2TextNode = z.object({
  ...V2Envelope,
  type: z.literal("Text"),
  props: z
    .object({
      content: z.string().optional(),
      // Extended to cover inline tags the LLM consistently emits (`small`,
      // `div`, `li`, `blockquote`, `code`). Renderer treats unknown values
      // as `span` via the underlying primitive, so wider acceptance here
      // costs nothing and matches generated schemas.
      as: z
        .enum([
          "span", "p", "h1", "h2", "h3", "h4", "h5", "h6",
          "label", "strong", "em", "small", "div", "li",
          "blockquote", "code",
        ])
        .default("span"),
      // Typography props the LLM consistently emits — the renderer maps them to
      // utility classes; accepting them avoids "unrecognized key" noise.
      variant: z.string().optional(),
      weight: z.union([z.string(), z.number()]).optional(),
      color: z.string().optional(),
      size: z.union([z.string(), z.number()]).optional(),
      align: z.string().optional(),
    })
    .strict()
    .optional(),
});

const V2ImageNode = z.object({
  ...V2Envelope,
  type: z.literal("Image"),
  props: z
    .object({
      src: z.string().min(1),
      alt: z.string(),
      width: z.number().int().positive().optional(),
      height: z.number().int().positive().optional(),
    })
    .strict(),
});

const V2RepeatNode = z.object({
  ...V2Envelope,
  type: z.literal("Repeat"),
  // The LLM emits Repeat in two equivalent shapes:
  //   { type: "Repeat", bind: "requests", children: [...] }   — top-level bind
  //   { type: "Repeat", props: { source, as, keyPath }, ... } — explicit props
  // Runtime accepts both (see `nodes/data/Repeat.tsx`). Make props optional so
  // the bind-only shape parses, and make `source` optional inside since `bind`
  // can supply the source name instead.
  props: z
    .object({
      source: z.string().min(1).optional(),
      path: z.string().optional(),
      as: z.string().default("item"),
      keyPath: z.string().default("id"),
    })
    .strict()
    .optional(),
  children: z.array(NodeV2Ref).min(1),
});

const V2ConditionalNode = z.object({
  ...V2Envelope,
  type: z.literal("Conditional"),
  props: z.object({ when: Expression }).strict(),
  children: z.array(NodeV2Ref).min(1),
  else: z.array(NodeV2Ref).optional(),
});

const V2DataBoundaryNode = z.object({
  ...V2Envelope,
  type: z.literal("DataBoundary"),
  props: z
    .object({
      fallback: z.string().optional(),
      bind: z.string().optional(),
      source: z.string().optional(),
    })
    .strict()
    .optional(),
  children: z.array(NodeV2Ref).default([]),
});

const V2SlotNode = z.object({
  id: z.string().min(1),
  type: z.literal("Slot"),
  props: z.object({ name: z.string().min(1) }).strict(),
});

// ── Library bridge nodes ──
// These 13 component types are registered at runtime in the scaffold/editor's
// renderer registry (Button, Link, Badge, Alert, Form, Table, …) but had no
// matching node schema in NodeV2 — so any LLM-generated page that used them
// (which is essentially all of them) failed validation with an
// "Invalid discriminator value" error.
//
// Each bridge node accepts arbitrary props (`z.record(z.unknown())`) — the
// runtime LibraryDispatcher does its own per-component prop validation via
// `registry.validateProps` against the library's Zod schema, so the
// authoritative shape lives there. The bridge here only confirms the node
// exists in the union and carries the standard envelope fields.
// Factory must preserve the literal type in its return so each result is a
// valid ZodDiscriminatedUnionOption<"type">. Inferring through ZodRawShape
// drops the literal, so we declare each node inline below using the same
// pattern. Two flavours: leaf (no children) and container (lazy children).
const _leaf = <T extends string>(typeName: T) =>
  z.object({
    ...V2Envelope,
    type: z.literal(typeName),
    props: z.record(z.unknown()).optional(),
  }).strict();
const _container = <T extends string>(typeName: T) =>
  z.object({
    ...V2Envelope,
    type: z.literal(typeName),
    props: z.record(z.unknown()).optional(),
    children: z.lazy(() => z.array(NodeV2Ref)).default([]),
  }).strict();

const ButtonNode       = _leaf("Button");
const LinkNode         = _leaf("Link");
const NavLinkNode      = _leaf("NavLink");
const IconButtonNode   = _leaf("IconButton");
const TabPanelNode     = _container("TabPanel");
const BadgeNode        = _leaf("Badge");
const DividerNode      = _leaf("Divider");
const BreadcrumbNode   = _leaf("Breadcrumb");
const AlertNode        = _leaf("Alert");
const EmptyStateNode   = _leaf("EmptyState");
const LoadingStateNode = _leaf("LoadingState");
const TableNode        = _leaf("Table");
const FormNode         = _container("Form");

// NodeV2 union — v2 types first, then structural v1-compat. Built as a
// `z.discriminatedUnion("type", …)` rather than `z.union(…)` so each child
// position resolves to a single branch in O(1) via the `type` literal lookup.
//
// `z.union` over ~40 recursive branches is catastrophic on large schema
// trees: every child position retries every branch, and each failed branch
// constructs a deep ZodError tree, which combined with `z.lazy()`-driven
// recursion explodes into multi-GB allocation and OOMs the SSR worker on
// trees as small as ~30 nodes (caught while rendering Mark 2 schemas in
// the scaffold). Discriminated union dispatches by `type` literal and skips
// the speculative work entirely.
export const NodeV2: z.ZodTypeAny = z.lazy(() => {
  const union = z.discriminatedUnion("type", [
    // strict v2 node types
    CustomNode,
    HeroNode,
    SectionNode,
    MetricTileNode,
    FeatureCardNode,
    CardNode,
    HeadingNode,
    SplitNode,
    SidebarNode,
    ClusterNode,
    TabsNodePlain,
    AccordionNode,
    AccordionPanelNode,
    AvatarNode,
    KeyValueListNode,
    SkeletonNodePlain,
    InputNode,
    SelectNode,
    TextareaNode,
    CheckboxNode,
    SwitchNode,
    NumberInputNode,
    RadioGroupNode,
    SliderNode,
    FileUploadNode,
    ComboboxNode,
    DatePickerNode,
    TimePickerNode,
    ColorPickerNode,
    InputOTPNode,
    RatingNode,
    MaskedInputNode,
    KeyValueInputNode,
    DropdownMenuNode,
    PopoverNode,
    TooltipNode,
    DrawerNode,
    ContextMenuNode,
    HoverCardNode,
    MenubarNode,
    FadeInNode,
    StaggerNode,
    // Tier 2 — data visualisation + display
    ChartNode,
    SparklineNode,
    DataGridNode,
    TimelineNode,
    GaugeNode,
    HeatmapNode,
    SchematicNode,
    // Tier 2 — enterprise components (batch 2)
    ApprovalStepperNode,
    StepperNode,
    PersonCardNode,
    FilterBarNode,
    CommandPaletteNode,
    ActivityFeedNode,
    // Tier 2 — enterprise components (batch 3)
    EmptyStateRichNode,
    DateRangePickerNode,
    MultiSelectNode,
    // Tier 2 Wave 4 — layout primitives
    AppShellNode,
    InspectorPanelNode,
    TabPanelWithDeepLinkNode,
    // Wave 3 — feedback
    ProgressNode,
    SpinnerNode,
    BannerNode,
    // Wave 4 — data display
    TagNode,
    StatNode,
    DescriptionListNode,
    ListNode,
    SegmentedControlNode,
    TreeNode,
    TransferNode,
    CascaderNode,
    // Wave 5 — heavy composites
    CalendarNode,
    KanbanNode,
    ResourceTimelineNode,
    RichTextEditorNode,
    CarouselNode,
    LightboxNode,
    CodeBlockNode,
    QRCodeNode,
    // Wave 6 — device & capture
    CameraCaptureNode,
    BarcodeScannerNode,
    ScannerNode,
    ValidationChecklistNode,
    // structural v1-compat nodes (with NodeV2Ref children)
    V2StackNode,
    V2RowNode,
    V2GridNode,
    V2ContainerNode,
    V2SpacerNode,
    V2BoxNode,
    V2TextNode,
    V2ImageNode,
    V2RepeatNode,
    V2ConditionalNode,
    V2DataBoundaryNode,
    V2SlotNode,
    // Library bridge nodes — match runtime registry types so LLM-emitted
    // schemas validate. Per-component prop validation lives in the library
    // package and runs via LibraryDispatcher at render time.
    ButtonNode,
    LinkNode,
    NavLinkNode,
    IconButtonNode,
    TabPanelNode,
    BadgeNode,
    DividerNode,
    BreadcrumbNode,
    AlertNode,
    EmptyStateNode,
    LoadingStateNode,
    TableNode,
    FormNode,
  ]);
  // Re-apply cross-field invariants that the standalone TabsNode / SkeletonNode
  // exports enforce via `.refine()`. Doing it here, on the discriminated union
  // (rather than on the individual ZodObject members), keeps each member a
  // plain ZodObject — the precondition that lets z.discriminatedUnion dispatch
  // by `type` literal in O(1). The refine itself is still O(1) per node since
  // it only branches on `node.type`.
  const refined = union.superRefine((node, ctx) => {
    if (node.type === "Tabs") {
      const n = node as { children: unknown[]; props: { tabs: unknown[] } };
      if (n.children.length !== n.props.tabs.length) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Tabs.children length must match Tabs.props.tabs length",
          path: ["children"],
        });
      }
    } else if (node.type === "Skeleton") {
      const n = node as { props: { variant: string; lines?: number } };
      if (n.props.lines !== undefined && n.props.variant !== "text") {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Skeleton.lines is only valid when variant is 'text'",
          path: ["props", "lines"],
        });
      }
    }
  });
  // Wire the forward ref so NodeV2Ref (in node-ref.ts) resolves to the refined
  // union. After this call, any z.lazy(() => NodeV2Ref) in the node files will
  // validate children against the full strict union with cross-field checks.
  setNodeV2Ref(refined);
  return refined;
});

// ============================================================================
// PageV2
// ============================================================================
export const PageV2 = z.object({
  schemaVersion: z.literal("2"),
  id: z.string().min(1),
  route: z.string().min(1),
  layout: z.string().min(1).optional(),
  meta: z.record(z.any()).default({}),
  dataSources: z.array(z.any()).default([]),
  root: NodeV2,
});
export type PageV2T = z.infer<typeof PageV2>;

// ============================================================================
// Page: discriminated union on schemaVersion
//
// Callers that previously imported `Page` and passed schemaVersion:"1" objects
// continue to work — PageV1 handles "1", PageV2 handles "2".
// ============================================================================
export const Page = z.discriminatedUnion("schemaVersion", [PageV1, PageV2]);
export type PageT = z.infer<typeof Page>;

// Legacy type alias — kept for backward compatibility with code that used
// `Page` as a type (not just a schema value).
export type Page = PageT;
