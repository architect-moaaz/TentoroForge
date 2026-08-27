import { z } from "zod";

/**
 * CartPanel — reads GET /api/cart and renders the current user's cart items,
 * subtotal, quantity controls, and a checkout button. Suitable for a full page
 * (CartPage wraps this) or a drawer/sheet.
 */
export const CartPanelProps = z.object({
  title:             z.string().optional(),
  emptyState:        z.string().optional(),
  currency:          z.string().optional(),
  checkoutLabel:     z.string().optional(),
  paymentMethods:    z.array(z.string()).optional(),
  onCheckoutNavigate: z.string().optional(),
  className:         z.string().optional(),
  style:             z.record(z.unknown()).optional(),
});
export type CartPanelPropsType = z.infer<typeof CartPanelProps>;
