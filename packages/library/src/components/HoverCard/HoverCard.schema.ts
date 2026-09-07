import { z } from "zod";
export const HoverCardProps = z.object({
  label:     z.string().default("Hover"),
  title:     z.string().optional(),
  content:   z.string().default(""),
  /**
   * Placement and hover intent. None of these four existed in any layer, which
   * left HoverCard the only floating surface in the library with no way to move
   * it (Tooltip has `side`, Popover has `align`) and no way to stop it popping
   * on the slightest mouse-over. All optional: absent keeps Radix's own
   * conventional defaults.
   */
  side:       z.enum(["top", "right", "bottom", "left"]).optional(),
  align:      z.enum(["start", "center", "end"]).optional(),
  openDelay:  z.number().int().min(0).max(5000).optional(),
  closeDelay: z.number().int().min(0).max(5000).optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type HoverCardPropsType = z.infer<typeof HoverCardProps>;
