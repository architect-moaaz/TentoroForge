import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const OverlayCardProps = z
  .object({
    title:       z.string().optional(),
    description: z.string().optional(),
    elevation:   z.enum(["sm", "md", "lg", "xl"]).default("lg"),
    anchor:      z
      .enum(["top-left", "top-right", "bottom-left", "bottom-right", "center"])
      .default("bottom-right"),
    offset:      z.string().default("-3rem"),
    style:       StyleSlot.optional(),
  })
  .strict();

export type OverlayCardPropsType = z.infer<typeof OverlayCardProps>;
