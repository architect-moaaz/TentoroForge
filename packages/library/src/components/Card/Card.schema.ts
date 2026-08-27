import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const CardProps = z
  .object({
    title: z.string().optional(),
    footer: z.string().optional(),
    elevation: z.enum(["none", "sm", "md", "lg"]).default("sm"),
    style: StyleSlot.optional(),
  })
  .strict();

export type CardPropsType = z.infer<typeof CardProps>;
