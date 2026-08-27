import { z } from "zod";
export const TooltipProps = z.object({
  label:     z.string().default("Hover"),
  content:   z.string().default(""),
  side:      z.enum(["top", "right", "bottom", "left"]).optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type TooltipPropsType = z.infer<typeof TooltipProps>;
