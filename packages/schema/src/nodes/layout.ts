import { z } from "zod";
import { TokenRef, StyleProps } from "../tokens";
import { Expression, EventHandler, EventName, DataBinding } from "../expressions";
import { Node } from "./index";

const Envelope = {
  id: z.string().min(1),
  style: StyleProps.optional(),
  bind: DataBinding.optional(),
  visibleIf: Expression.optional(),
  on: z.record(EventName, EventHandler).optional(),
};

// Forward-declared Node ref — ESM circular import is safe with z.lazy because
// Zod defers resolution until parse time, by which point nodes/index.ts is
// fully loaded.
const NodeRef: z.ZodTypeAny = z.lazy(() => Node);

export const StackNode = z
  .object({
    ...Envelope,
    type: z.literal("Stack"),
    props: z
      .object({
        direction: z.enum(["vertical", "horizontal"]).default("vertical"),
        gap: TokenRef.optional(),
        align: z.enum(["start", "center", "end", "stretch"]).default("stretch"),
        justify: z.enum(["start", "center", "end", "between", "around"]).default("start"),
        wrap: z.boolean().optional(),
      })
      .strict()
      .optional(),
    children: z.array(NodeRef).default([]),
  })
  .strict();

export const RowNode = z
  .object({
    ...Envelope,
    type: z.literal("Row"),
    props: z
      .object({
        gap: TokenRef.optional(),
        align: z.enum(["start", "center", "end", "stretch"]).default("center"),
        justify: z.enum(["start", "center", "end", "between", "around"]).default("start"),
        wrap: z.boolean().optional(),
      })
      .strict()
      .optional(),
    children: z.array(NodeRef).default([]),
  })
  .strict();

export const GridNode = z
  .object({
    ...Envelope,
    type: z.literal("Grid"),
    props: z
      .object({
        columns: z.number().int().min(1).max(12),
        gap: TokenRef.optional(),
        // Codifies the iteration-3 v4 spike CSS fix: optional layout-evenness
        // booleans so schemas can declare intent and the renderer guarantees
        // even rows / columns without depending on hand-injected globals.css.
        // - equalRows: emits `grid-auto-rows: 1fr` so mixed-content rows are
        //   forced to equal height (closes the "uneven KPI tiles" look).
        // - equalCols: switches from `repeat(N, 1fr)` to
        //   `repeat(N, minmax(0, 1fr))` so children are *truly* equal width
        //   (without minmax, large children expand their column and break
        //   distribution).
        equalRows: z.boolean().optional(),
        equalCols: z.boolean().optional(),
      })
      .strict(),
    children: z.array(NodeRef).default([]),
  })
  .strict();

export const ContainerNode = z
  .object({
    ...Envelope,
    type: z.literal("Container"),
    props: z
      .object({
        maxWidth: z.enum(["sm", "md", "lg", "xl", "2xl", "full"]).default("lg"),
      })
      .strict()
      .optional(),
    children: z.array(NodeRef).default([]),
  })
  .strict();

export const SpacerNode = z
  .object({
    ...Envelope,
    type: z.literal("Spacer"),
    props: z.object({ size: TokenRef }).strict(),
  })
  .strict();

export const LayoutNode = z.discriminatedUnion("type", [
  StackNode,
  RowNode,
  GridNode,
  ContainerNode,
  SpacerNode,
]);

export type LayoutNode = z.infer<typeof LayoutNode>;
