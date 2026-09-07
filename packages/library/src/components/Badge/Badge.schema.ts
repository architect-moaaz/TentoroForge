import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const BadgeProps = z
  .object({
    // Optional: the Figma mapper emits content-less status pills (just a
    // coloured className chip). Badge renders an empty pill in that case
    // rather than failing validation.
    content: z.string().optional(),
    // "accent" is the second brand hue. `Badge.tsx` has always typed it in
    // `Variant` and carried a full `VARIANT_CLASS` row for it, and the registry
    // offers it in the VARIANT select — but this enum was the narrower
    // five-value list, so `validateProps` stripped `accent` back to the
    // parameter default and the control silently did nothing. Widened to the
    // six values the component actually implements.
    variant: z
      .enum(["neutral", "primary", "accent", "success", "danger", "warning"])
      .default("neutral"),
    style: StyleSlot.optional(),
  })
  .strict();

export type BadgePropsType = z.infer<typeof BadgeProps>;
