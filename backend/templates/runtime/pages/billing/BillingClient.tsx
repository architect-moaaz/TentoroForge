"use client";

/**
 * The billing page's moving parts: choose a plan (the gateway's page opens),
 * cancel at the period's end, manage the card at the gateway, and wait —
 * visibly — while a new subscription is confirmed. Forge runtime.
 */
import { useEffect, useMemo, useState } from "react";

interface Plan { id: string; name: string; description?: string; interval: string; intervalCount: number; prices: Record<string, number>;
  trialDays: number; features: string[]; highlighted?: boolean }
interface Sub { id: string; plan: string; status: string; provider: string; currency: string; amountMinor: number; interval: string;
  currentPeriodEnd: string | null; cancelAtPeriodEnd: boolean }

const base = () => (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
const ZERO = new Set(["JPY", "KRW", "VND", "CLP", "UGX", "XAF", "XOF"]);
const THREE = new Set(["BHD", "JOD", "KWD", "OMR", "TND"]);

function money(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: ZERO.has(currency) ? 0 : THREE.has(currency) ? 3 : 2,
      minimumFractionDigits: Number.isInteger(amount) && !THREE.has(currency) ? 0 : undefined }).format(amount);
  } catch {
    return `${amount} ${currency}`;
  }
}
const minorToMajor = (m: number, c: string) => ZERO.has(c) ? m : THREE.has(c) ? m / 1000 : m / 100;
function every(interval: string, count: number): string {
  const unit = { day: "day", week: "week", month: "month", year: "year" }[interval] ?? interval;
  return count > 1 ? `every ${count} ${unit}s` : `/ ${unit}`;
}
function date(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
}
const STATUS: Record<string, { text: string; tone: string }> = {
  active: { text: "Active", tone: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200" },
  trialing: { text: "Trial", tone: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200" },
  past_due: { text: "Payment due", tone: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200" },
  paused: { text: "Paused", tone: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200" },
  cancelled: { text: "Cancelled", tone: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200" },
  expired: { text: "Ended", tone: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200" },
  incomplete: { text: "Not finished", tone: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200" },
};

export function BillingClient(props: { plans: Plan[]; currencies: string[]; currency: string; required: boolean; access: boolean; gateways: string[];
  subscription: Sub | null; flags: { welcome: boolean; pending: boolean; required: boolean; cancelled: boolean; problem: string; next: string };
  readProblem: string }) {
  const [currency, setCurrency] = useState(props.currency);
  const [sub, setSub] = useState<Sub | null>(props.subscription);
  const [access, setAccess] = useState(props.access);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState(props.readProblem);
  const [confirming, setConfirming] = useState(false);
  const [waiting, setWaiting] = useState(props.flags.pending);
  // Asked for a minute and still not confirmed: said so, and no second payment offered.
  const [slow, setSlow] = useState(false);
  const plan = useMemo(() => props.plans.find((p) => p.id === sub?.plan), [props.plans, sub]);

  // A NEW SUBSCRIPTION IS CONFIRMED BY THE GATEWAY, NOT THE CLICK: while it is,
  // this page asks again every few seconds (for a minute) and says so.
  useEffect(() => {
    if (!waiting) return;
    let n = 0;
    const t = setInterval(async () => {
      n += 1;
      try {
        const r = await fetch(`${base()}/api/billing/status`, { cache: "no-store" });
        const j = await r.json();
        if (j?.subscription) setSub(j.subscription);
        if (j?.access) { setAccess(true); setWaiting(false); clearInterval(t); }
      } catch { /* the next tick asks again */ }
      if (n >= 20) { setWaiting(false); setSlow(true); clearInterval(t); }
    }, 3000);
    return () => clearInterval(t);
  }, [waiting]);

  async function choose(planId: string) {
    setBusy(planId); setError("");
    try {
      const r = await fetch(`${base()}/api/billing/subscribe`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: planId, currency }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j?.url) throw new Error(j?.error || "The payment page could not be opened.");
      window.location.assign(j.url);
    } catch (e) {
      setError((e as Error).message); setBusy(null);
    }
  }
  async function cancel() {
    setBusy("cancel"); setError("");
    try {
      const r = await fetch(`${base()}/api/billing/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j?.error || "The subscription could not be cancelled.");
      setSub((s) => s ? { ...s, status: j.status, cancelAtPeriodEnd: Boolean(j.cancelAtPeriodEnd),
        currentPeriodEnd: j.currentPeriodEnd ? new Date(j.currentPeriodEnd).toISOString() : s.currentPeriodEnd } : s);
      setConfirming(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function manage() {
    setBusy("manage"); setError("");
    try {
      const r = await fetch(`${base()}/api/billing/manage`, { method: "POST" });
      const j = await r.json().catch(() => ({}));
      if (j?.url) { window.location.assign(j.url); return; }
      // "Managed with your bank" only when the gateway answered and has no
      // such page (Razorpay, PayPal); a failure is said as one (a down
      // database read as Stripe having no portal, 2026-11-11).
      setError(j?.error || (r.ok ? "Your payment method is managed with your bank or wallet for this gateway. To change it, cancel and subscribe again."
                                 : "The payment settings page could not be opened just now. Please try again in a moment."));
    } catch {
      setError("The payment settings page could not be opened. Check your connection and try again.");
    } finally {
      setBusy(null);
    }
  }

  const live = sub && (sub.status === "active" || sub.status === "trialing" || sub.status === "past_due" || (sub.status === "cancelled" && sub.cancelAtPeriodEnd)) && access;
  // A FAILED RENEWAL IS STILL SHOWN once its grace is over: the payer is told
  // what happened and what to do, not just "Choose a plan".
  const behind = sub?.status === "past_due" && !access;
  const amber = "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100";
  const sky = "border-sky-300 bg-sky-50 text-sky-900 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-100";
  // WHAT HAPPENED TO THEIR MONEY COMES FIRST: "Choose a plan" to someone whose
  // payment is still clearing is an invitation to pay twice.
  const banner = props.flags.welcome && access && !sub?.cancelAtPeriodEnd && sub?.status !== "cancelled" ? { tone: "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100",
      // A trial is said as a trial, with the day the first payment is taken.
      text: sub?.status === "trialing"
        ? `Your free trial${plan ? ` of ${plan.name}` : ""} has started${sub.currentPeriodEnd ? `. It runs until ${date(sub.currentPeriodEnd)}, and the first payment is taken then unless you cancel` : ""}.`
        : `You're subscribed${plan ? ` to ${plan.name}` : ""}. Thank you!` }
    : waiting ? { tone: sky, text: "Your payment is being confirmed with the gateway — this page updates on its own. There is no need to pay again." }
    : slow || props.flags.problem ? { tone: amber,
      text: "We could not confirm that payment yet. If money left your account, your plan will show here within a few minutes — please don't pay again. Refresh this page in a little while." }
    : behind ? { tone: amber, text: "Your last payment didn't go through, so your plan is paused until it does." }
    : props.flags.cancelled ? { tone: "border-border bg-muted text-foreground", text: "Checkout was cancelled. Nothing was charged." }
    : (props.flags.required || props.required) && !access ? { tone: amber, text: "Choose a plan to continue." }
    : null;
  const hold = waiting || slow;

  return (
    <main className="mx-auto w-full max-w-5xl space-y-8 p-6" data-forge-billing="">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Plan &amp; billing</h1>
        <p className="mt-1 text-sm text-muted-foreground">Your subscription, and the plans you can choose from.</p>
      </header>

      {banner && <div role="status" data-billing-banner="" className={`rounded-lg border p-4 text-sm ${banner.tone}`}>{banner.text}
        {props.flags.welcome && access && props.flags.next && <a href={`${base()}${props.flags.next}`} className="ml-2 font-medium underline">Continue</a>}</div>}
      {error && <div role="alert" data-billing-error="" className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950/40 dark:text-red-100">{error}</div>}

      {(live || behind) && sub && (
        <section data-billing-current="" className="rounded-xl border border-border bg-card p-6 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Your plan</p>
              <h2 className="mt-1 flex items-center gap-2 text-xl font-semibold">{plan?.name ?? sub.plan}
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${(STATUS[sub.status] ?? STATUS.incomplete).tone}`}>
                  {sub.status === "cancelled" || sub.cancelAtPeriodEnd ? "Ending" : (STATUS[sub.status] ?? STATUS.incomplete).text}</span></h2>
              <p className="mt-1 text-sm text-muted-foreground">{money(minorToMajor(sub.amountMinor, sub.currency), sub.currency)} {every(sub.interval, plan?.intervalCount ?? 1)}
                {sub.provider === "stand_in" ? " · test subscription, nobody was charged" : ""}</p>
              {sub.currentPeriodEnd && (
                <p className="mt-2 text-sm">{sub.cancelAtPeriodEnd || sub.status === "cancelled"
                  ? <>Your access ends on <b>{date(sub.currentPeriodEnd)}</b>. You won't be charged again.</>
                  : sub.status === "trialing" ? <>Your trial ends on <b>{date(sub.currentPeriodEnd)}</b>.</>
                  : <>Renews on <b>{date(sub.currentPeriodEnd)}</b>.</>}</p>
              )}
              {sub.status === "past_due" && <p className="mt-2 text-sm text-amber-700 dark:text-amber-300">Your last payment didn't go through. {sub.provider === "stripe"
                ? "The gateway will try again; update your payment method to keep your access."
                : "The gateway will try again. If it keeps failing, cancel and subscribe again with another card or account."}</p>}
            </div>
            <div className="flex flex-wrap gap-2">
              {sub.provider === "stripe" && <button type="button" onClick={manage} disabled={busy !== null} className="rounded-md border border-border px-3 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50">{busy === "manage" ? "Opening…" : "Manage payment method"}</button>}
              {!sub.cancelAtPeriodEnd && sub.status !== "cancelled" && (confirming ? (
                <span className="flex items-center gap-2 rounded-md border border-border p-1 pl-3 text-sm">Cancel at the end of this period?
                  <button type="button" data-billing-cancel-yes="" onClick={cancel} disabled={busy !== null} className="rounded bg-red-600 px-2.5 py-1.5 font-medium text-white disabled:opacity-50">{busy === "cancel" ? "Cancelling…" : "Yes, cancel"}</button>
                  <button type="button" onClick={() => setConfirming(false)} className="rounded px-2 py-1.5 hover:bg-muted">Keep it</button></span>
              ) : <button type="button" data-billing-cancel="" onClick={() => setConfirming(true)} className="rounded-md px-3 py-2 text-sm font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40">Cancel subscription</button>)}
            </div>
          </div>
        </section>
      )}

      <section aria-label="Plans" className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-lg font-semibold">{live ? "Change plan" : "Choose a plan"}</h2>
          {props.currencies.length > 1 && (
            <label className="flex items-center gap-2 text-sm text-muted-foreground">Pay in
              <select value={currency} onChange={(e) => setCurrency(e.target.value)} data-billing-currency="" aria-label="Pay in" className="rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground">
                {props.currencies.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
          )}
        </div>
        {live && <p className="text-sm text-muted-foreground">A new plan starts straight away; your current plan stops renewing and you will not be charged for it again.</p>}
        <div className={`grid gap-4 ${props.plans.length >= 3 ? "md:grid-cols-3" : props.plans.length === 2 ? "md:grid-cols-2" : ""}`}>
          {props.plans.map((p) => {
            const price = p.prices[currency];
            // THE PLAN THAT IS ENDING IS STILL THEIRS until it ends: taking it
            // again would charge now for a period already paid for.
            const mine = live && sub?.plan === p.id;
            const ending = mine && (sub?.cancelAtPeriodEnd || sub?.status === "cancelled");
            return (
              <div key={p.id} data-billing-plan={p.id} className={`relative flex flex-col rounded-xl border bg-card p-6 shadow-sm ${p.highlighted ? "border-primary ring-1 ring-primary" : "border-border"}`}>
                {p.highlighted && <span className="absolute -top-3 left-6 rounded-full bg-primary px-2.5 py-0.5 text-xs font-medium text-primary-foreground">Most popular</span>}
                <h3 className="text-base font-semibold">{p.name}</h3>
                {p.description && <p className="mt-1 text-sm text-muted-foreground">{p.description}</p>}
                <p className="mt-4">{price != null ? <><span className="text-3xl font-bold tracking-tight">{money(price, currency)}</span>
                  <span className="ml-1 text-sm text-muted-foreground">{every(p.interval, p.intervalCount)}</span></>
                  : <span className="text-sm text-muted-foreground">Not offered in {currency}</span>}</p>
                {p.trialDays > 0 && <p className="mt-1 text-xs font-medium text-primary">{p.trialDays}-day free trial</p>}
                {p.features.length > 0 && (
                  <ul className="mt-4 flex-1 space-y-2 text-sm">
                    {p.features.map((f) => <li key={f} className="flex gap-2"><span aria-hidden className="text-primary">✓</span>{f}</li>)}
                  </ul>
                )}
                <button type="button" data-billing-choose={p.id} onClick={() => choose(p.id)} disabled={mine || price == null || busy !== null || hold}
                        className={`mt-6 rounded-md px-4 py-2.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60 ${p.highlighted ? "bg-primary text-primary-foreground hover:opacity-90" : "border border-border hover:bg-muted"}`}>
                  {ending ? (sub?.currentPeriodEnd ? `Yours until ${date(sub.currentPeriodEnd)}` : "Ending") : mine ? "Your current plan"
                    : busy === p.id ? "Opening secure checkout…" : live ? `Switch to ${p.name}` : p.trialDays > 0 ? "Start free trial" : `Choose ${p.name}`}
                </button>
              </div>
            );
          })}
        </div>
        <p className="text-xs text-muted-foreground">
          Payments are processed securely by {props.gateways.length ? props.gateways.join(" and ") : "the payment gateway"}. Your card and bank details never reach this app. Cancel any time; you keep access until the end of what you paid for.
        </p>
      </section>
    </main>
  );
}
