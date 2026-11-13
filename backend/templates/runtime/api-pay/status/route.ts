/**
 * GET /api/pay/status?payment=<id> — where a one-time payment stands, asked
 * of its gateway: what the confirming page waits on. Once it is settled, the
 * page the process named (paid) or its cancel page (not paid), as the ledger
 * holds them — never an address from the request. Outside the sign-in gate,
 * as a guest's checkout is. Forge runtime — do not remove.
 */
import { NextResponse } from "next/server";
import { initializeRuntime } from "@/lib/runtime-loader";

export const runtime = "nodejs";

export async function GET(req: Request) {
  await initializeRuntime();
  const id = String(new URL(req.url).searchParams.get("payment") ?? "");
  if (!/^[0-9a-f-]{36}$/i.test(id)) return NextResponse.json({ error: "no such payment" }, { status: 404 });
  const pay = await import("@/lib/payments");
  const out = await pay.confirmPayment(id, {});
  if (!out.row) return NextResponse.json({ error: "no such payment" }, { status: 404 });
  const status = out.row.status;
  const target = status === "succeeded" ? out.row.success_url
    : status === "failed" || status === "cancelled" ? out.row.cancel_url ?? out.row.success_url : null;
  let redirect: string | null = null;
  if (target) {
    const dest = new URL(target);
    dest.searchParams.set("payment", out.row.id);
    dest.searchParams.set("status", status);
    redirect = dest.toString();
  }
  return NextResponse.json({ status, redirect }, { headers: { "Cache-Control": "no-store" } });
}
