import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const DividerProps = z
  .object({
    orientation: z.enum(["horizontal", "vertical"]).default("horizontal"),
    style: StyleSlot.optional(),
  })
  .strict();

export type DividerPropsType = z.infer<typeof DividerProps>;
