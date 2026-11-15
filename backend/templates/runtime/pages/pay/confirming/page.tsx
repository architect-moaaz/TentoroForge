/**
 * /pay/confirming?payment=<id> — where a payer waits while the gateway
 * confirms a payment it has not settled yet (a bank transfer still clearing,
 * a slow answer). Never the cancel page: a payer told "not paid" after paying
 * pays again. Forge runtime — do not edit by hand.
 */
import { ConfirmingPayment } from "./ConfirmingPayment";

export const dynamic = "force-dynamic";

export default async function Confirming({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const id = String(Array.isArray(sp.payment) ? sp.payment[0] : sp.payment ?? "");
  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/40 p-6">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 text-center shadow-sm">
        <ConfirmingPayment id={id} />
      </div>
    </main>
  );
}
