/**
 * POST /api/cart/checkout — freeze the current user's cart, fire the
 * `cart.checkout` workflow event with { items, subtotal, userId }, and clear
 * the cart. If any user-defined workflow subscribes to that event (order
 * persistence, email receipt, notification, payment kickoff), it runs there;
 * the runtime itself only handles the cart mechanic. Forge runtime — do not
 * remove.
 */
import { NextResponse } from "next/server";
import { db } from "@/db";
import { forgeCart } from "@/db/schema/_forge_cart";
import { auth } from "@/auth";
import { eq } from "drizzle-orm";
import { triggerWorkflowEvent } from "@/lib/workflows";
import { initializeRuntime } from "@/lib/runtime-loader";

export const runtime = "nodejs";

export async function POST(req: Request): Promise<Response> {
  await initializeRuntime();
  try {
    const session = await auth();
    const su = session?.user as { id?: string; role?: string; email?: string | null } | undefined;
    if (!su?.id) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    const userId = su.id;

    const rows = await db.select().from(forgeCart).where(eq(forgeCart.userId, userId));
    if (rows.length === 0) {
      return NextResponse.json({ ok: false, error: "cart is empty" }, { status: 400 });
    }

    const items = rows.map((r) => ({
      itemRef: r.itemRef,
      quantity: r.quantity,
      price: r.priceSnapshot == null ? null : Number(r.priceSnapshot),
      label: r.label,
    }));
    let subtotal = 0;
    for (const it of items) {
      if (typeof it.price === "number" && Number.isFinite(it.price)) subtotal += it.price * (it.quantity || 0);
    }
    subtotal = Math.round(subtotal * 100) / 100;

    const body = await req.json().catch(() => ({}));
    const payload = {
      items,
      subtotal,
      userId,
      paymentMethod: body?.paymentMethod ?? null,
      shippingAddress: body?.shippingAddress ?? null,
      note: body?.note ?? null,
    };

    // Fire the checkout event. Workflows that don't exist yet are a no-op.
    let workflowResults: unknown = null;
    try {
      workflowResults = await triggerWorkflowEvent(
        "cart.checkout",
        payload,
        { id: userId, role: su.role, email: su.email ?? undefined },
      );
    } catch (err) {
      console.error("[api/cart/checkout] workflow trigger", err);
    }

    // Clear the cart after firing (whether or not a workflow claimed it).
    try {
      await db.delete(forgeCart).where(eq(forgeCart.userId, userId));
    } catch (err) {
      console.error("[api/cart/checkout] clear", err);
    }

    return NextResponse.json({ ok: true, subtotal, itemCount: items.length, workflowResults });
  } catch (err) {
    console.error("[api/cart/checkout] POST", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
