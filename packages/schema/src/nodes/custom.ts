import { z } from "zod";
import { StyleSlot } from "../style-slot";

export const CustomNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Custom"),
  props: z.object({
    html: z.string().min(1, "Custom node requires non-empty html"),
    tailwind: z.string().optional(),
    label: z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type CustomNodeT = z.infer<typeof CustomNode>;
