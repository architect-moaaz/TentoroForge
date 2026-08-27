import { z } from "zod";
import { StyleProps } from "../tokens";
import { Expression, EventHandler, EventName, DataBinding } from "../expressions";
import { Node } from "./index";

const RESERVED = new Set([
  "Stack", "Row", "Grid", "Container", "Spacer",
  "Box", "Text", "Image",
  "Repeat", "Conditional", "DataBoundary",
  "Slot",
]);

// Forward-declared Node ref — ESM circular import is safe with z.lazy because
// Zod defers resolution until parse time, by which point nodes/index.ts is
// fully loaded.
const NodeRef: z.ZodTypeAny = z.lazy(() => Node);

export const LibraryNode = z
  .object({
    id: z.string().min(1),
    type: z.string().min(1).refine((t) => !RESERVED.has(t), {
      message: "type collides with a reserved (non-library) node bucket",
    }),
    props: z.record(z.unknown()).optional(),
    style: StyleProps.optional(),
    bind: DataBinding.optional(),
    visibleIf: Expression.optional(),
    on: z.record(EventName, EventHandler).optional(),
    children: z.array(NodeRef).optional(),
  })
  .strict();

export type LibraryNode = z.infer<typeof LibraryNode>;
