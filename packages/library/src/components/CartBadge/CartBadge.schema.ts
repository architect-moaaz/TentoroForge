import { z } from "zod";

/**
 * CartBadge — reads GET /api/cart and shows a count pill. Meant to live in the
 * app shell (nav/topbar). Clicking navigates to `href` (defaults to /cart).
 */
export const CartBadgeProps = z.object({
  href:      z.string().optional(),
  label:     z.string().optional(),
  hideZero:  z.boolean().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type CartBadgePropsType = z.infer<typeof CartBadgeProps>;
