import { z } from "zod";
import { StyleProps } from "../tokens";
import { Expression, EventHandler, EventName, DataBinding } from "../expressions";
import { Node } from "./index";

// Forward-declared Node ref — ESM circular import is safe with z.lazy because
// Zod defers resolution until parse time, by which point nodes/index.ts is
// fully loaded.
const NodeRef: z.ZodTypeAny = z.lazy(() => Node);

const Envelope = {
  id: z.string().min(1),
  style: StyleProps.optional(),
  bind: DataBinding.optional(),
  visibleIf: Expression.optional(),
  on: z.record(EventName, EventHandler).optional(),
};

export const RepeatNode = z
  .object({
    ...Envelope,
    type: z.literal("Repeat"),
    props: z
      .object({
        source: z.string().min(1),
        path: z.string().optional(),
        as: z.string().default("item"),
        keyPath: z.string().default("id"),
      })
      .strict(),
    children: z.array(NodeRef).min(1, "Repeat requires at least one child template"),
  })
  .strict();

export const ConditionalNode = z
  .object({
    ...Envelope,
    type: z.literal("Conditional"),
    props: z.object({ when: Expression }).strict(),
    children: z.array(NodeRef).min(1),
    else: z.array(NodeRef).optional(),
  })
  .strict();

export const DataBoundaryNode = z
  .object({
    ...Envelope,
    type: z.literal("DataBoundary"),
    props: z
      .object({
        fallback: z.string().optional(),
      })
      .strict()
      .optional(),
    children: z.array(NodeRef).default([]),
  })
  .strict();

export const DataNode = z.discriminatedUnion("type", [RepeatNode, ConditionalNode, DataBoundaryNode]);
export type DataNode = z.infer<typeof DataNode>;
