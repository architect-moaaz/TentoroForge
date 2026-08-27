import { z } from "zod";

/**
 * AddToCart — posts to /api/cart to insert (or increment) a cart line for the
 * current user. `entity` + `itemId` uniquely identify the product row across
 * the app's schema so cart mechanics stay decoupled from the entity name.
 * `price` and `label` are snapshotted at add-time (display stability). No
 * per-app schema is needed; the runtime primitive owns cart state.
 */
export const AddToCartProps = z.object({
  entity:   z.string(),
  itemId:   z.union([z.string(), z.number()]),
  quantity: z.number().optional(),
  price:    z.union([z.number(), z.string()]).optional(),
  label:    z.string().optional(),
  text:     z.string().optional(),
  variant:  z.enum(["primary", "secondary", "ghost", "outline"]).optional(),
  size:     z.enum(["sm", "md", "lg"]).optional(),
  fullWidth: z.boolean().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type AddToCartPropsType = z.infer<typeof AddToCartProps>;
