import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const BadgeProps = z
  .object({
    // Optional: the Figma mapper emits content-less status pills (just a
    // coloured className chip). Badge renders an empty pill in that case
    // rather than failing validation.
    content: z.string().optional(),
    variant: z
      .enum(["neutral", "primary", "success", "danger", "warning"])
      .default("neutral"),
    style: StyleSlot.optional(),
  })
  .strict();

export type BadgePropsType = z.infer<typeof BadgeProps>;
