/**
 * /pay/razorpay — where a payer pays through Razorpay: its Checkout window
 * (UPI, cards, netbanking, wallets; a mandate for a subscription) opened over
 * the application's own page. What Razorpay answers is checked on the server
 * (`/api/pay/confirm`) before anything is believed. Only the key ID — public
 * by design — reaches the browser. Forge runtime — do not edit by hand.
 */
import { sql } from "drizzle-orm";
import { db } from "@/db";
import { auth } from "@/auth";
import { RazorpayCheckout } from "./RazorpayCheckout";

export const dynamic = "force-dynamic";

const rows = (r: any) => (Array.isArray(r) ? r : r?.rows ?? []);

export default async function RazorpayPay({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const one = (k: string) => String(Array.isArray(sp[k]) ? sp[k]![0] : sp[k] ?? "");
  const keyId = String(process.env.RAZORPAY_KEY_ID ?? "");
  const name = String(process.env.NEXT_PUBLIC_APP_NAME ?? process.env.FORGE_APP_NAME ?? "");
  // A local check against the gateway emulator opens its stand-in of the
  // window; anywhere else, Razorpay's own script (never set in production).
  const emulator = String(process.env.FORGE_PAY_EMULATOR ?? "").replace(/\/$/, "");
  const script = emulator ? `${emulator}/razorpay/checkout.js` : undefined;
  const paymentId = one("payment");
  const subscriptionId = one("subscription");
  // `gatewayRef`, never `ref`: React keeps that name for itself and refuses a
  // server page that hands one to a client component (the page failed whole).
  let props: any = null;
  let problem = "";
  try {
    if (paymentId && /^[0-9a-f-]{36}$/i.test(paymentId)) {
      const row = rows(await db.execute(sql`SELECT id, provider, provider_ref, status, amount_minor, currency, description, success_url FROM forge_payments WHERE id = ${paymentId}::uuid LIMIT 1`))[0];
      if (!row || row.provider !== "razorpay") problem = "This payment is not waiting for Razorpay.";
      else if (row.status === "succeeded") props = { done: row.success_url };
      else props = { kind: "payment", id: row.id, gatewayRef: row.provider_ref, amountMinor: Number(row.amount_minor), currency: row.currency, description: row.description ?? "" };
    } else if (subscriptionId && /^[0-9a-f-]{36}$/i.test(subscriptionId)) {
      const session = await auth();
      const uid = String((session?.user as any)?.id ?? "");
      const row = rows(await db.execute(sql`SELECT id, user_id, provider, provider_ref, status, plan_id FROM forge_subscriptions WHERE id = ${subscriptionId}::uuid LIMIT 1`))[0];
      if (!row || row.provider !== "razorpay" || row.user_id !== uid) problem = "This subscription is not waiting for Razorpay.";
      else props = { kind: "subscription", id: row.id, gatewayRef: row.provider_ref, plan: row.plan_id,
        email: (session?.user as any)?.email ?? "", userName: (session?.user as any)?.name ?? "" };
    } else {
      problem = "Nothing to pay here.";
    }
  } catch (err) {
    console.error("[pay] razorpay page:", err);
    problem = "The payment could not be read just now. Please go back and try again.";
  }
  if (!keyId && !problem) problem = "Razorpay is not set up where this app runs.";
  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/40 p-6">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-sm">
        {problem ? <p role="alert" className="text-sm">{problem}</p>
          : <RazorpayCheckout keyId={keyId} appName={name} script={script} {...props} />}
      </div>
    </main>
  );
}
