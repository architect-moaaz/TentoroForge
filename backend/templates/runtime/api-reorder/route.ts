/**
 * PATCH /api/data/[entity]/reorder — Spec E Wave 1.
 *
 * Body: { ids: string[], newOrder?: number[] }
 *   - `ids`      — the current visible ordering (top-first).
 *   - `newOrder` — optional explicit sort-order values, same length as `ids`.
 *                  Falls back to positional index * 1000 when omitted so
 *                  future inserts can slot between rows without a global renumber.
 *
 * The route relies on the Data Engine catch-all's registered entities +
 * assumes a `sortOrder` INTEGER column exists on the target entity —
 * `services/reorder_column_pass.py` adds it whenever the planner
 * declares a Table `reorderable`.
 *
 * Forge runtime — do not remove.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";

export const runtime = "nodejs";

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ entity: string }> | { entity: string } },
): Promise<Response> {
  try {
    const session = await auth().catch(() => null);
    if (!session?.user) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }

    const { entity } = (await Promise.resolve(params)) as { entity: string };
    const body = (await req.json().catch(() => ({}))) as {
      ids?: unknown;
      newOrder?: unknown;
    };
    const ids = Array.isArray(body.ids) ? (body.ids as unknown[]).map(String) : [];
    if (ids.length === 0) {
      return NextResponse.json({ error: "ids[] required" }, { status: 400 });
    }
    const newOrder =
      Array.isArray(body.newOrder) && body.newOrder.length === ids.length
        ? (body.newOrder as unknown[]).map((n) => Number(n) || 0)
        : ids.map((_, i) => (i + 1) * 1000);

    // Reflective update so this route stays entity-agnostic. Requires
    // the Data Engine's `update()` helper to accept a partial patch keyed
    // on the primary column.
    const engine = await import("@/lib/data-engine").catch(() => null);
    if (!engine || typeof (engine as any).update !== "function") {
      return NextResponse.json(
        { error: "data-engine unavailable" },
        { status: 500 },
      );
    }

    const updated: Array<{ id: string; sortOrder: number }> = [];
    for (let i = 0; i < ids.length; i += 1) {
      const id = ids[i];
      const sortOrder = newOrder[i];
      try {
        await (engine as any).update(entity, id, { sortOrder });
        updated.push({ id, sortOrder });
      } catch (err) {
        console.error("[api/data/reorder] update failed", entity, id, err);
      }
    }

    return NextResponse.json({ ok: true, entity, updated });
  } catch (err) {
    console.error("[api/data/reorder] PATCH", err);
    return NextResponse.json({ error: "internal_error" }, { status: 500 });
  }
}
