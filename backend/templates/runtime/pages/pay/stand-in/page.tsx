/**
 * The stand-in checkout: what a person sees when the application takes a
 * payment — or starts a subscription — before a gateway's key is set (a
 * preview, the test version without test keys). Shows the amount or the
 * plan; "Paid" and "Failed" settle it the way the gateway's signed event
 * would. Nobody is charged, and the page says so.
 * Forge runtime — do not edit by hand.
 */
import { sql } from "drizzle-orm";
import { db } from "@/db";
import { liveSide } from "@/lib/payments";

export const dynamic = "force-dynamic";

const rows = (r: any) => (Array.isArray(r) ? r : r?.rows ?? []);
const ZERO = new Set(["BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"]);
const THREE = new Set(["BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"]);
const major = (minor: number, c: string) => (ZERO.has(c) ? minor : THREE.has(c) ? minor / 1000 : minor / 100);
const shown = (minor: number, c: string) => {
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency: c }).format(major(minor, c)); } catch { return `${major(minor, c)} ${c}`; }
};

export default async function StandInCheckout({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const one = (k: string) => String(Array.isArray(sp[k]) ? sp[k]![0] : sp[k] ?? "");
  const base = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
  const session = one("session");
  const subscription = one("subscription");
  let row: any = null;
  let kind: "payment" | "subscription" = "payment";
  try {
    if (subscription && /^[0-9a-f-]{36}$/i.test(subscription)) {
      kind = "subscription";
      row = rows(await db.execute(sql`SELECT id, plan_id, amount_minor, currency, interval, status FROM forge_subscriptions WHERE id = ${subscription}::uuid AND provider = 'stand_in' LIMIT 1`))[0] ?? null;
    } else {
      const id = session.replace(/^standin_/, "");
      if (/^[0-9a-f-]{36}$/i.test(id)) {
        row = rows(await db.execute(sql`SELECT id, amount_minor, currency, description, status FROM forge_payments WHERE id = ${id}::uuid LIMIT 1`))[0] ?? null;
      }
    }
  } catch { row = null; }
  const waiting = row && (kind === "subscription" ? row.status === "incomplete" : row.status === "pending");
  const live = liveSide();
  // What the person reads, in words: "succeeded" is the ledger's.
  const STATE: Record<string, string> = { succeeded: "paid", active: "active", trialing: "active", cancelled: "cancelled",
    failed: "not paid", expired: "ended", refunded: "refunded", partially_refunded: "partly refunded" };
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md rounded-lg border border-border p-6 shadow-sm" data-stand-in={kind}>
        <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Test checkout · nobody is charged</p>
        {live ? (
          <p role="alert">Payments are not switched on in this app yet, so nothing was charged. Please try again later.</p>
        ) : !row ? (
          <p>There is nothing to pay here.</p>
        ) : !waiting ? (
          <p>This {kind} is {STATE[String(row.status)] ?? String(row.status)} already.</p>
        ) : (
          <>
            <h1 className="mb-1 text-2xl font-semibold">{shown(Number(row.amount_minor), String(row.currency))}
              {kind === "subscription" && <span className="text-base font-normal text-muted-foreground"> / {row.interval}</span>}</h1>
            <p className="mb-6 text-sm text-muted-foreground">{kind === "subscription" ? `Subscription to ${row.plan_id}` : row.description || "Payment"}</p>
            <p className="mb-4 text-sm">No payment gateway is connected where this copy runs, so nothing is charged. Choose what the real checkout would have answered.</p>
            <form method="post" action={`${base}/api/pay/stand-in`} className="flex gap-2">
              <input type="hidden" name={kind === "subscription" ? "subscription" : "session"} value={kind === "subscription" ? subscription : session} />
              <button name="outcome" value="paid" className="rounded bg-primary px-4 py-2 text-primary-foreground">{kind === "subscription" ? "Subscribed" : "Paid"}</button>
              <button name="outcome" value="failed" className="rounded border border-border px-4 py-2">Failed</button>
            </form>
          </>
        )}
        <a href={`${base}/`} className="mt-6 inline-block text-sm text-muted-foreground underline">Back to the app</a>
      </div>
    </main>
  );
}
