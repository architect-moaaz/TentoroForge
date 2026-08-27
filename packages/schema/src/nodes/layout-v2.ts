import { z } from "zod";
import { StyleSlot } from "../style-slot";
import { SpacingTokenRef } from "../tokens";
import { NodeV2Ref } from "../node-ref";

export const SplitNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Split"),
  props: z.object({
    ratio: z.enum(["1:1", "2:1", "1:2", "1:3", "3:1"]),
    breakpoint: z.enum(["sm", "md", "lg"]).optional(),
  }).strict(),
  style: StyleSlot.optional(),
  // children recurse through NodeV2Ref (forward reference from page.ts) so
  // any unknown node type in a child position is rejected by the union.
  children: z.lazy(() => z.array(NodeV2Ref).length(2, "Split must have exactly 2 children")),
}).strict();
export type SplitNodeT = z.infer<typeof SplitNode>;

export const SidebarNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Sidebar"),
  props: z.object({
    width: z.string().regex(/^\d+(?:px|rem|%)$/),
  }).strict(),
  style: StyleSlot.optional(),
  // children recurse through NodeV2Ref (forward reference from page.ts) so
  // any unknown node type in a child position is rejected by the union.
  children: z.lazy(() => z.array(NodeV2Ref).length(2, "Sidebar must have exactly 2 children (sidebar + main)")),
}).strict();
export type SidebarNodeT = z.infer<typeof SidebarNode>;

export const ClusterNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Cluster"),
  props: z.object({
    gap:     SpacingTokenRef.optional(),
    justify: z.enum(["start", "center", "end", "between"]).default("start"),
    align:   z.enum(["start", "center", "end", "stretch"]).default("center"),
    // Codifies the iteration-3 v4 spike CSS fix as an explicit schema prop.
    // The default flex+flex-wrap+justify-between Cluster gives content-sized
    // children — KPI/metric tile rows look visibly uneven because each tile
    // shrinks to fit its label/value. When equalCols is true the renderer
    // switches the underlying display to CSS grid with
    // `grid-template-columns: repeat(N, minmax(0, 1fr))` (N = children
    // count) for true equal-width distribution. equalRows is accepted on
    // Cluster for parity with Grid (so a single prop set works when
    // schemas swap one for the other) and applies `grid-auto-rows: 1fr`
    // when the grid path is active.
    equalCols: z.boolean().optional(),
    equalRows: z.boolean().optional(),
  }).strict(),
  style: StyleSlot.optional(),
  // children recurse through NodeV2Ref (forward reference from page.ts) so
  // any unknown node type in a child position is rejected by the union.
  children: z.lazy(() => z.array(NodeV2Ref)).default([]),
}).strict();
export type ClusterNodeT = z.infer<typeof ClusterNode>;

// TabDef is tab metadata only — id, label, optional icon. The rendered
// content for each tab lives in TabsNode.children at the same array index.
// This is intentionally a flat data record (not a Node-shaped object)
// because the tab header doesn't have its own children/style/refine surface.
const TabDef = z.object({
  id: z.string().min(1).optional(),
  label: z.string().min(1),
  icon: z.string().optional(),
}).strict();

export const TabsNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Tabs"),
  props: z.object({
    tabs:  z.array(TabDef).min(1),
    value: z.string().min(1),
  }).strict(),
  style: StyleSlot.optional(),
  // children recurse through NodeV2Ref (forward reference from page.ts) so
  // any unknown node type in a child position is rejected by the union.
  children: z.lazy(() => z.array(NodeV2Ref)),
}).strict()
// Refine fires only after the inner schema parses successfully. If
// props.tabs fails .min(1), the count check never runs (and the user
// sees the props-level error first, which is the right ordering).
  .refine((n) => n.children.length === n.props.tabs.length,
    { message: "Tabs.children length must match Tabs.props.tabs length",
      path: ["children"] });
export type TabsNodeT = z.infer<typeof TabsNode>;

// AccordionPanelNode is exported as a schema value (so AccordionNode can
// reference it in `children: z.array(AccordionPanelNode)`), but no `*T`
// type alias is exported — derive from `AccordionNodeT["children"][number]`
// when needed. This matches the "internal helper" convention.
export const AccordionPanelNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("AccordionPanel"),
  props: z.object({
    label: z.string().min(1),
    value: z.string().min(1),
  }).strict(),
  // children recurse through NodeV2Ref (forward reference from page.ts) so
  // any unknown node type in a child position is rejected by the union.
  children: z.lazy(() => z.array(NodeV2Ref)).default([]),
}).strict();

export const AccordionNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Accordion"),
  // NOTE: defaultOpen[i] should reference an actual panel id from
  // children[].props.value. That integrity check is performed by
  // cross-ref-validator.ts, not by the node schema itself — keep this
  // schema concerned only with shape, not cross-field semantics.
  props: z.object({
    mode: z.enum(["single", "multi"]),
    defaultOpen: z.array(z.string()).default([]),
  }).strict(),
  style: StyleSlot.optional(),
  children: z.array(AccordionPanelNode).default([]),
}).strict();
export type AccordionNodeT = z.infer<typeof AccordionNode>;
