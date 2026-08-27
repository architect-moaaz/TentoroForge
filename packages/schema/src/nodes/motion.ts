import { z } from "zod";
import { StyleSlot } from "../style-slot";
import { NodeV2Ref } from "../node-ref";

// Motion nodes are the only v2 nodes that use `props: ...strict().default({})`.
// They have zero required props, so this lets the LLM emit
// `{ id, type, children }` without an empty `props: {}` literal. Every other
// v2 node has at least one required prop, so a `props: {}` literal would be
// a parse error there and `.default({})` would be dead code. See plan §Task 7.

export const FadeInNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("FadeIn"),
  props: z.object({
    delay:    z.number().int().nonnegative().optional(),
    duration: z.number().int().positive().optional(),
  }).strict().default({}),
  style: StyleSlot.optional(),
  // children recurse through NodeV2Ref (forward reference from page.ts) so
  // any unknown node type in a child position is rejected by the union.
  children: z.lazy(() => z.array(NodeV2Ref)).default([]),
}).strict();
export type FadeInNodeT = z.infer<typeof FadeInNode>;

export const StaggerNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Stagger"),
  props: z.object({
    delay:    z.number().int().nonnegative().optional(),
    // 80ms ≈ Material Design / Framer Motion default stagger interval; the
    // CSS-side default in Task 10's useMotion / Task 18's motion stylesheet
    // must match this value or schema-default and runtime-default will drift.
    interval: z.number().int().positive().default(80),
  }).strict().default({}),
  style: StyleSlot.optional(),
  // children recurse through NodeV2Ref (forward reference from page.ts) so
  // any unknown node type in a child position is rejected by the union.
  children: z.lazy(() => z.array(NodeV2Ref)).default([]),
}).strict();
export type StaggerNodeT = z.infer<typeof StaggerNode>;
