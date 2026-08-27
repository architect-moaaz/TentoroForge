import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const DialogProps = z
  .object({
    id: z.string().min(1),
    title: z.string().optional(),
    description: z.string().optional(),
    size: z.enum(["sm", "md", "lg", "xl"]).optional(),
    className: z.string().optional(),
    style: StyleSlot.optional(),
  })
  .strict();

export type DialogPropsType = z.infer<typeof DialogProps>;
