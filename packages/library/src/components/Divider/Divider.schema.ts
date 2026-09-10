import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const DividerProps = z
  .object({
    orientation: z.enum(["horizontal", "vertical"]).default("horizontal"),
    // `thickness` has been a `select` control in the registry since the entry
    // was written, but it was missing here — so validateProps stripped it and
    // the control was dead (docs/editor-audit/containment.md, feature-gaps:
    // "The control exists and does nothing"). Declared here, it reaches the
    // component and picks a real stroke.
    thickness: z.enum(["thin", "medium", "thick"]).default("thin"),
    style: StyleSlot.optional(),
  })
  .strict();

export type DividerPropsType = z.infer<typeof DividerProps>;
