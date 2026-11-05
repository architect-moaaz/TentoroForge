/**
 * /billing — the signed-in person's plan: what they hold, when it renews or
 * ends, and every plan the application sells, in their currency. The gateway
 * is never trusted from the browser: subscribing opens the gateway's own
 * page, and what comes back is read from the gateway on the server.
 * Inside the application's own frame. Forge runtime — do not edit by hand.
 */
import { headers } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { PAYMENTS } from "@/lib/payments-config";
import { BillingClient } from "./BillingClient";

export const dynamic = "force-dynamic";

export default async function BillingPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const session = await auth();
  const uid = String((session?.user as any)?.id ?? "");
  if (!uid) redirect("/login");
  const sp = await searchParams;
  const one = (k: string) => String(Array.isArray(sp[k]) ? sp[k]![0] : sp[k] ?? "");
  const billing = await import("@/lib/payments/billing");
  // An app that sells no plans has no billing page.
  if (!billing.subscriptionsOffered()) notFound();
  const { countryOf } = await import("@/lib/payments/routing");
  const h = await headers();
  let row: any = null;
  let ok = false;
  let problem = "";
  try {
    const out = await billing.hasAccess(uid);
    row = out.row;
    ok = out.ok;
  } catch (err) {
    console.error("[billing] page could not read the subscription:", err);
    problem = "Your plan could not be read just now. Refresh the page in a moment.";
  }
  const list = billing.priceList(countryOf(h));
  // By the gateway's own name: "Stripe Global" is the owner's label for an account, not what a payer knows.
  const NAMES: Record<string, string> = { stripe: "Stripe", razorpay: "Razorpay", paypal: "PayPal" };
  const gateways = Array.from(new Set((PAYMENTS?.gateways ?? []).map((g: any) => NAMES[String(g.provider)] ?? String(g.label || g.provider))));
  // Where they were going, back inside this app only.
  const nextRaw = one("next");
  const next = nextRaw.startsWith("/") && !nextRaw.startsWith("//") && !nextRaw.includes("\\") ? nextRaw : "";
  return (
    <BillingClient
      plans={billing.plans()}
      currencies={list.currencies}
      currency={list.currency}
      required={billing.accessRequired()}
      access={ok}
      gateways={gateways}
      subscription={row ? { id: row.id, plan: row.plan_id, status: row.status, provider: row.provider, currency: row.currency,
        amountMinor: Number(row.amount_minor), interval: row.interval,
        currentPeriodEnd: row.current_period_end ? new Date(row.current_period_end).toISOString() : null,
        cancelAtPeriodEnd: Boolean(row.cancel_at_period_end) } : null}
      flags={{ welcome: one("welcome") === "1", pending: one("pending") === "1", required: one("required") === "1",
        cancelled: one("cancelled") === "1", problem: one("problem"), next }}
      readProblem={problem}
    />
  );
}
