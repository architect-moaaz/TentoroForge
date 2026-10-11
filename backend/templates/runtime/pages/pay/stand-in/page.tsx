/**
 * The stand-in checkout: what a person sees when the application takes a
 * payment before a provider's key is set. Shows the amount; "Paid" and
 * "Failed" settle the ledger the way the provider's signed event would.
 * Forge runtime — do not edit by hand.
 */
import { sql } from "drizzle-orm";
import { db } from "@/db";

export const dynamic = "force-dynamic";

export default async function StandInCheckout({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const session = String(Array.isArray(sp.session) ? sp.session[0] : sp.session ?? "");
  const id = session.replace(/^standin_/, "");
  let row: any = null;
  try {
    const res: any = await db.execute(sql`SELECT id, amount_minor, currency, description, status FROM forge_payments WHERE id = ${id}::uuid LIMIT 1`);
    row = (Array.isArray(res) ? res : res?.rows ?? [])[0] ?? null;
  } catch { row = null; }
  const zero = new Set(["BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"]);
  const amount = row ? (zero.has(String(row.currency)) ? Number(row.amount_minor) : Number(row.amount_minor) / 100) : 0;
  const shown = row ? new Intl.NumberFormat(undefined, { style: "currency", currency: String(row.currency) }).format(amount) : "";
  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-md rounded-lg border border-border p-6 shadow-sm">
        <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">Stand-in checkout</p>
        {!row ? (
          <p>No such payment.</p>
        ) : row.status !== "pending" ? (
          <p>This payment is already {row.status}.</p>
        ) : (
          <>
            <h1 className="text-2xl font-semibold mb-1">{shown}</h1>
            <p className="text-sm text-muted-foreground mb-6">{row.description || "Payment"}</p>
            <p className="text-sm mb-4">No payment service is connected yet, so nothing is charged. Choose what the real checkout would have answered.</p>
            <form method="post" action="/api/pay/stand-in" className="flex gap-2">
              <input type="hidden" name="session" value={session} />
              <button name="outcome" value="paid" className="rounded bg-primary text-primary-foreground px-4 py-2">Paid</button>
              <button name="outcome" value="failed" className="rounded border border-border px-4 py-2">Failed</button>
            </form>
          </>
        )}
      </div>
    </main>
  );
}
