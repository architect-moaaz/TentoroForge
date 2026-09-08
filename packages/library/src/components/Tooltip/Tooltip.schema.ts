import { z } from "zod";
export const TooltipProps = z.object({
  label:     z.string().default("Hover"),
  content:   z.string().default(""),
  side:      z.enum(["top", "right", "bottom", "left"]).optional(),
  /**
   * Hover intent in ms before the hint opens. `Tooltip.tsx` hardwired
   * `delayDuration={0}`, so every Tooltip in every generated app fired the
   * instant the pointer crossed it and there was no way, in any layer, to
   * author the conventional intent window. Same shape and same bounds as
   * `HoverCard.openDelay`, which was fixed first.
   */
  delayMs:   z.number().int().min(0).max(5000).optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type TooltipPropsType = z.infer<typeof TooltipProps>;
