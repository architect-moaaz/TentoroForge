import { z } from "zod";

/**
 * CartPage — page-shell composition of the cart. Wraps CartPanel with a Heading
 * and page padding so the schema author can drop a single node for `/cart`.
 */
export const CartPageProps = z.object({
  title:             z.string().optional(),
  emptyState:        z.string().optional(),
  currency:          z.string().optional(),
  checkoutLabel:     z.string().optional(),
  paymentMethods:    z.array(z.string()).optional(),
  onCheckoutNavigate: z.string().optional(),
  className:         z.string().optional(),
  style:             z.record(z.unknown()).optional(),
});
export type CartPagePropsType = z.infer<typeof CartPageProps>;
