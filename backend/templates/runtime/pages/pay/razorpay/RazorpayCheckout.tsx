"use client";

/**
 * Opens Razorpay's Checkout window and hands its answer to the server. A
 * closed window is not a failure: the payer can open it again. Forge runtime.
 */
import { useCallback, useEffect, useRef, useState } from "react";

declare global { interface Window { Razorpay?: any } }

const base = () => (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
const SCRIPT = "https://checkout.razorpay.com/v1/checkout.js";

function load(src: string = SCRIPT): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src; s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Razorpay's checkout could not be loaded. Check your connection and try again."));
    document.body.appendChild(s);
  });
}

export function RazorpayCheckout(p: { keyId: string; appName?: string; script?: string; kind?: "payment" | "subscription"; id?: string; gatewayRef?: string;
  amountMinor?: number; currency?: string; description?: string; plan?: string; email?: string; userName?: string; done?: string }) {
  const [state, setState] = useState<"loading" | "open" | "confirming" | "closed" | "failed">("loading");
  const [said, setSaid] = useState("");
  const opened = useRef(false);

  const confirm = useCallback(async (answer: Record<string, string>) => {
    setState("confirming");
    try {
      const r = await fetch(`${base()}/api/pay/confirm`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...(p.kind === "subscription" ? { subscription: p.id } : { payment: p.id }), ...answer }) });
      const j = await r.json().catch(() => ({}));
      if (j?.redirect) { window.location.assign(j.redirect); return; }
      throw new Error(j?.error || "The payment could not be confirmed.");
    } catch (e) {
      setSaid((e as Error).message); setState("failed");
    }
  }, [p.id, p.kind]);

  const open = useCallback(async () => {
    setSaid("");
    try {
      await load(p.script);
      const rzp = new window.Razorpay({
        key: p.keyId,
        ...(p.kind === "subscription" ? { subscription_id: p.gatewayRef } : { order_id: p.gatewayRef, amount: p.amountMinor, currency: p.currency }),
        name: p.appName || undefined,
        description: p.description || undefined,
        prefill: { email: p.email || undefined, name: p.userName || undefined },
        handler: (res: Record<string, string>) => void confirm(res),
        modal: { ondismiss: () => setState((s) => (s === "confirming" ? s : "closed")) },
      });
      rzp.on("payment.failed", (resp: any) => {
        setSaid(resp?.error?.description || "The payment did not go through. You can try again.");
      });
      rzp.open();
      setState("open");
    } catch (e) {
      setSaid((e as Error).message); setState("failed");
    }
  }, [p, confirm]);

  useEffect(() => {
    if (p.done) { window.location.assign(p.done); return; }
    if (!opened.current) { opened.current = true; void open(); }
  }, [open, p.done]);

  const div = p.currency && ["JPY", "KRW", "VND", "CLP"].includes(p.currency) ? 1 : p.currency && ["BHD", "JOD", "KWD", "OMR", "TND"].includes(p.currency) ? 1000 : 100;
  const amount = p.amountMinor != null && p.currency
    ? new Intl.NumberFormat(undefined, { style: "currency", currency: p.currency }).format(p.amountMinor / div) : "";
  return (
    <div className="space-y-4 text-center" data-razorpay-state={state}>
      <p className="text-xs uppercase tracking-wide text-muted-foreground">Secure payment · Razorpay</p>
      {amount && <p className="text-2xl font-semibold">{amount}</p>}
      {p.description && <p className="text-sm text-muted-foreground">{p.description}</p>}
      {state === "loading" && <p className="text-sm">Opening Razorpay…</p>}
      {state === "open" && <p className="text-sm">Complete the payment in the Razorpay window.</p>}
      {state === "confirming" && <p className="text-sm">Confirming your payment with Razorpay…</p>}
      {(state === "closed" || state === "failed") && (
        <>
          <p className="text-sm">{said || "The payment window was closed. Nothing was charged."}</p>
          <button type="button" onClick={() => void open()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">Open payment again</button>
          <p><button type="button" onClick={() => history.back()} className="text-sm text-muted-foreground underline">Go back</button></p>
        </>
      )}
    </div>
  );
}
