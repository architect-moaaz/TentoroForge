/**
 * POST /api/billing/subscribe {plan, currency?} — begin a subscription for the
 * signed-in person: the gateway for their currency (and country), the plan
 * made at it once, and where they go to authorise it. Forge runtime.
 */
import { NextResponse } from "next/server";
import { initializeRuntime } from "@/lib/runtime-loader";
import { countryOf } from "@/lib/payments/routing";
import { originOf, person } from "../_session";

export const runtime = "nodejs";

export async function POST(req: Request) {
  await initializeRuntime();
  const who = await person();
  if (!who) return NextResponse.json({ error: "Sign in to subscribe." }, { status: 401 });
  const body: any = await req.json().catch(() => ({}));
  const plan = String(body?.plan ?? "").trim();
  if (!plan) return NextResponse.json({ error: "Choose a plan." }, { status: 400 });
  try {
    const billing = await import("@/lib/payments/billing");
    const out = await billing.subscribe({ user: who, planId: plan, currency: body?.currency ? String(body.currency) : undefined,
      country: countryOf(req.headers), origin: originOf(req) });
    return NextResponse.json(out);
  } catch (err) {
    const said = String((err as Error)?.message ?? err);
    console.error("[billing] subscribe failed:", said);
    const known = /no plan|no price|already hold|cannot take/.test(said);
    return NextResponse.json({ error: known ? said.charAt(0).toUpperCase() + said.slice(1) + "."
      : "The payment page could not be opened. Please try again in a moment." }, { status: known ? 400 : 502 });
  }
}
