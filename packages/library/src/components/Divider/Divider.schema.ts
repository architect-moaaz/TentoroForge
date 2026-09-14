import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const DividerProps = z
  .object({
    orientation: z.enum(["horizontal", "vertical"]).default("horizontal"),
    // Declared by the registry with a live select. The schema is .strict(), so
    // without this line validateProps stripped it before Divider ever saw it —
    // the editor control wrote a value that could not reach the component.
    thickness: z.enum(["thin", "medium", "thick"]).optional(),
    style: StyleSlot.optional(),
  })
  .strict();

export type DividerPropsType = z.infer<typeof DividerProps>;
