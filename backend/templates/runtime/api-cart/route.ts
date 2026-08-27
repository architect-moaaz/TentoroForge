/**
 * GET  /api/cart          — the current user's cart rows + subtotal.
 * POST /api/cart          — add or increment an item (upsert by userId+itemRef).
 * PATCH /api/cart         — set quantity for a row ({ id, quantity }); 0 removes.
 * DELETE /api/cart?id=... — remove a row.
 * Forge runtime — do not remove.
 */
import { NextResponse } from "next/server";
import { db } from "@/db";
import { forgeCart } from "@/db/schema/_forge_cart";
import { auth } from "@/auth";
import { and, eq, sql } from "drizzle-orm";

export const runtime = "nodejs";

async function currentUserId(): Promise<string | null> {
  try {
    const session = await auth();
    const su = session?.user as { id?: string } | undefined;
    return su?.id ?? null;
  } catch {
    return null;
  }
}

function subtotal(rows: Array<{ quantity: number; priceSnapshot: string | number | null }>): number {
  let total = 0;
  for (const r of rows) {
    const p = r.priceSnapshot == null ? 0 : Number(r.priceSnapshot);
    if (Number.isFinite(p)) total += p * (r.quantity || 0);
  }
  return Math.round(total * 100) / 100;
}

export async function GET(): Promise<Response> {
  const userId = await currentUserId();
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const rows = await db.select().from(forgeCart).where(eq(forgeCart.userId, userId));
    return NextResponse.json({
      items: rows,
      count: rows.reduce((acc, r) => acc + (r.quantity || 0), 0),
      subtotal: subtotal(rows as any),
    });
  } catch (err) {
    console.error("[api/cart] GET", err);
    return NextResponse.json({ items: [], count: 0, subtotal: 0 });
  }
}

export async function POST(req: Request): Promise<Response> {
  const userId = await currentUserId();
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const body = await req.json().catch(() => ({}));
    const entity = String(body?.entity || "").trim();
    const itemId = body?.itemId != null ? String(body.itemId) : "";
    if (!entity || !itemId) {
      return NextResponse.json({ error: "entity and itemId required" }, { status: 400 });
    }
    const itemRef = { entity, id: itemId };
    const quantity = Math.max(1, Number(body?.quantity ?? 1) | 0);
    const price = body?.price == null ? null : String(body.price);
    const label = body?.label == null ? null : String(body.label);

    const existing = await db
      .select()
      .from(forgeCart)
      .where(and(eq(forgeCart.userId, userId), sql`${forgeCart.itemRef} = ${JSON.stringify(itemRef)}::jsonb`))
      .limit(1);

    if (existing.length > 0) {
      const row = existing[0];
      await db
        .update(forgeCart)
        .set({ quantity: (row.quantity || 0) + quantity, updatedAt: new Date() })
        .where(eq(forgeCart.id, row.id));
    } else {
      await db.insert(forgeCart).values({
        userId,
        itemRef,
        quantity,
        priceSnapshot: price as any,
        label,
      });
    }
    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error("[api/cart] POST", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function PATCH(req: Request): Promise<Response> {
  const userId = await currentUserId();
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const body = await req.json().catch(() => ({}));
    const id = String(body?.id || "");
    const quantity = Number(body?.quantity ?? 0) | 0;
    if (!id) return NextResponse.json({ error: "id required" }, { status: 400 });
    if (quantity <= 0) {
      await db.delete(forgeCart).where(and(eq(forgeCart.id, id), eq(forgeCart.userId, userId)));
    } else {
      await db
        .update(forgeCart)
        .set({ quantity, updatedAt: new Date() })
        .where(and(eq(forgeCart.id, id), eq(forgeCart.userId, userId)));
    }
    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error("[api/cart] PATCH", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function DELETE(req: Request): Promise<Response> {
  const userId = await currentUserId();
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const { searchParams } = new URL(req.url);
    const id = searchParams.get("id") || "";
    if (id) {
      await db.delete(forgeCart).where(and(eq(forgeCart.id, id), eq(forgeCart.userId, userId)));
    } else {
      await db.delete(forgeCart).where(eq(forgeCart.userId, userId));
    }
    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error("[api/cart] DELETE", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
