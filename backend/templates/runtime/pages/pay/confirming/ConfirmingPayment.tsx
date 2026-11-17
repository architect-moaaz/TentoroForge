"use client";

/**
 * Asks where the payment stands every few seconds and goes on the moment it
 * is settled. After a minute it stops asking and says what happens next —
 * money that left the payer's account is not lost. Forge runtime.
 */
import { useEffect, useState } from "react";

const base = () => (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
const EVERY_MS = 3000;
const TRIES = 20;

export function ConfirmingPayment({ id }: { id: string }) {
  const [state, setState] = useState<"waiting" | "slow" | "missing">(id ? "waiting" : "missing");

  useEffect(() => {
    if (!id) return;
    let alive = true;
    let tries = 0;
    const ask = async () => {
      tries += 1;
      try {
        const r = await fetch(`${base()}/api/pay/status?payment=${encodeURIComponent(id)}`, { cache: "no-store" });
        if (r.status === 404) { if (alive) setState("missing"); return; }
        const j = await r.json().catch(() => ({}));
        if (j?.redirect) { window.location.assign(j.redirect); return; }
      } catch { /* a dropped connection: asked again */ }
      if (!alive) return;
      if (tries >= TRIES) { setState("slow"); return; }
      setTimeout(ask, EVERY_MS);
    };
    void ask();
    return () => { alive = false; };
  }, [id]);

  if (state === "missing") {
    return <p role="alert">There is no payment to confirm here. <a className="underline" href={`${base()}/`}>Back to the app</a></p>;
  }
  return (
    <div aria-live="polite">
      <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Secure payment</p>
      {state === "waiting" ? (
        <>
          <h1 className="mb-2 text-lg font-semibold">Confirming your payment…</h1>
          <p className="text-sm text-muted-foreground">This takes a few seconds. Please keep this page open — there is no need to pay again.</p>
        </>
      ) : (
        <>
          <h1 className="mb-2 text-lg font-semibold">Your payment is still being confirmed</h1>
          <p className="mb-4 text-sm text-muted-foreground">Some payments take a few minutes to clear. If money left your account it is safe, and this
            payment will show as paid once it clears — please do not pay again.</p>
          <a className="text-sm underline" href={`${base()}/`}>Back to the app</a>
        </>
      )}
    </div>
  );
}
