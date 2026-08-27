import { z } from "zod";
import { LayoutNode } from "./layout";
import { PrimitiveNode } from "./primitive";
import { LibraryNode } from "./library";
import { DataNode } from "./data";
import { SlotNode } from "./slot";
import { PageOutletNode } from "./page-outlet";

// Layout, Primitive, Data are discriminated unions; LibraryNode is open-string;
// SlotNode is a literal. Order matters for fall-through: try exhaustive types
// first, then library as the open fallback.
export const Node: z.ZodTypeAny = z.lazy(() =>
  z.union([
    LayoutNode,
    PrimitiveNode,
    DataNode,
    SlotNode,
    PageOutletNode, // shell composition: replaced by page content at render time
    LibraryNode, // last: anything else with a non-reserved type
  ])
);

export type Node = z.infer<typeof Node>;

export { PageOutletNode } from "./page-outlet";
export type { PageOutletNodeT } from "./page-outlet";
