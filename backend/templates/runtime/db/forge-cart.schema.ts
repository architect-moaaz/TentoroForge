import { pgTable, uuid, text, integer, numeric, jsonb, timestamp, uniqueIndex } from "drizzle-orm/pg-core";

/**
 * Per-user shopping cart line items. A cart is the set of rows for a userId —
 * no separate "cart" table; the userId partition IS the cart. itemRef is the
 * addressable reference to the app entity being ordered ({ entity, id }); the
 * component that added the item passes it in verbatim so cart mechanics stay
 * decoupled from the app's schema. priceSnapshot / label freeze the display
 * values at add-time so the cart doesn't shift if the source row later changes.
 * Emitted by the Forge runtime — do not remove.
 */
export const forgeCart = pgTable(
  "forge_cart",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: text("user_id").notNull(),
    itemRef: jsonb("item_ref").notNull(),
    quantity: integer("quantity").notNull().default(1),
    priceSnapshot: numeric("price_snapshot", { precision: 12, scale: 2 }),
    label: text("label"),
    createdAt: timestamp("created_at").defaultNow(),
    updatedAt: timestamp("updated_at").defaultNow(),
  },
  (t) => ({
    userItemUnique: uniqueIndex("forge_cart_user_item_idx").on(t.userId, t.itemRef),
  }),
);
