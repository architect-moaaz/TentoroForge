"use client";

/**
 * An app's Payments tab: whether it takes money and why, through which of the
 * organisation's gateways (and who pays where), the plans it sells, and its
 * webhooks — with the one thing the owner does by hand (Razorpay's) laid out
 * to copy. Payments can be added to an app that had none, changed, or turned
 * off, any time.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight, CheckCircle2, Copy, CreditCard, ExternalLink, Info, MessageSquare, Pencil, Plus, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { GatewayMark } from "./GatewayMark";
import { PaymentChoiceDialog, paymentsApi, paymentsKey, type PaymentsView } from "./PaymentChoiceDialog";
import { STATUS_WORDS, routingLines } from "@/lib/payment-gateways";
import { askSmith } from "@/lib/ask-smith";

function copy(text: string, what: string) {
  void navigator.clipboard?.writeText(text).then(() => toast.success(`${what} copied.`), () => toast.error("Could not copy."));
}

function price(amount: number, currency: string): string {
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount); } catch { return `${amount} ${currency}`; }
}

export function PaymentsPanel({ projectId, orgId }: { projectId: string; orgId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: paymentsKey(projectId), queryFn: () => paymentsApi.get(projectId) });
  // Never worked out (an app from before payments, or nothing decided yet): Forge reads it now, on request.
  const decide = useMutation({
    mutationFn: () => paymentsApi.decide(projectId),
    onSuccess: (next) => qc.setQueryData(paymentsKey(projectId), next),
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "It could not be worked out just now."),
  });
  const [editing, setEditing] = useState(false);
  const v = q.data;
  const p = v?.payments;

  // h-full: the tab's own scroll (it grew past the frame, and the Razorpay
  // step at the bottom could not be reached).
  if (q.isLoading) return <div className="h-full p-8 text-sm text-muted-foreground">Loading…</div>;
  if (q.isError || !v || !p) {
    return <div className="h-full p-8 text-sm">{(q.error as Error)?.message || "This app has no definition yet — describe it to Smith first."}</div>;
  }
  const ready = v.readiness;
  const chosen = p.gateways.map((g) => v.gateways.find((x) => x.id === g.gateway) ?? null);
  const live = chosen.filter(Boolean) as NonNullable<(typeof chosen)[number]>[];
  const gone = p.gateways.filter((g, i) => !chosen[i]);

  return (
    <div className="h-full overflow-y-auto" data-payments-panel="">
    <div className="mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight"><CreditCard className="h-6 w-6" />Payments</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">How this app takes money, through which of your gateways, and what it sells.</p>
        </div>
        {p.needed ? (
          <Button variant="outline" onClick={() => setEditing(true)} data-edit-payments=""><Pencil className="mr-1.5 h-4 w-4" />Change</Button>
        ) : null}
      </div>

      {p.needed === null ? (
        <section className="rounded-xl border border-dashed p-6" data-payments-undecided="">
          <h2 className="text-base font-semibold">Not worked out yet</h2>
          <p className="mt-1 text-sm text-muted-foreground">Forge has not read whether this app takes money. It asks when the app is next built — or now.</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button onClick={() => decide.mutate()} disabled={decide.isPending} data-decide-payments="">
              {decide.isPending ? "Reading the app…" : "Work it out now"}</Button>
            <Button variant="outline" onClick={() => setEditing(true)}><Plus className="mr-1.5 h-4 w-4" />Choose payments myself</Button>
          </div>
        </section>
      ) : !p.needed ? (
        <section className="rounded-xl border border-dashed p-6" data-no-payments="">
          <h2 className="text-base font-semibold">This app takes no payments</h2>
          {p.reason && <p className="mt-1 text-sm text-muted-foreground">{p.reason}</p>}
          <p className="mt-3 text-sm">If it should sell something — orders, bookings, fees — or offer paid plans, add payments: choose which of your gateways it uses, and Forge builds them in.</p>
          <Button className="mt-4" onClick={() => setEditing(true)} data-add-payments=""><Plus className="mr-1.5 h-4 w-4" />Add payments to this app</Button>
        </section>
      ) : (
        <>
          {ready && ready.needed && !ready.liveReady && live.length > 0 && (
            // WHAT THE LIVE APP CANNOT DO YET, before anyone publishes it.
            <section role="status" data-payments-not-live="" className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="font-medium">Published as it is, this app cannot take real money yet.</p>
                <p className="mt-1">
                  {ready.missing.map((m) => `${m.label} ${m.removed ? "was removed" : m.state === "attention" ? "has keys its gateway refused" : m.state === "unchecked" ? "has live keys that were never confirmed" : "has no live keys"}`).join("; ")}.
                  {" "}Previews and the test version take test payments. In production, payers are told payments are not switched on and nobody is charged.
                </p>
                <a className="mt-2 inline-flex items-center gap-1 font-medium underline" href={`/org/${orgId}/settings/payments`}>Add live keys in Settings → Payments</a>
              </div>
            </section>
          )}
          <section className="rounded-xl border bg-card p-5 shadow-sm" data-payments-summary="">
            <p className="text-sm"><b>{p.models.map((m) => (m === "one_time" ? "One-time payments" : "Subscriptions")).join(" and ")}</b>
              {p.reason ? <span className="text-muted-foreground"> — {p.reason}</span> : null}</p>
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              {live.map((g) => (
                <div key={g.id} className="flex items-center gap-3 rounded-lg border p-3" data-app-gateway={g.provider}>
                  <GatewayMark provider={g.provider} size={32} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{g.label}</p>
                    <p className="text-xs text-muted-foreground">{STATUS_WORDS[g.status]} · {g.currencies.join(", ")}</p>
                  </div>
                </div>
              ))}
              {live.length === 0 && (
                <p className="text-sm text-muted-foreground sm:col-span-2" data-stand-in-note="">
                  No gateway chosen yet: the app uses a test checkout that charges nobody. <button type="button" className="text-primary underline" onClick={() => setEditing(true)}>Choose a gateway</button>
                </p>
              )}
            </div>
            {gone.length > 0 && (
              <p className="mt-3 flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-300"><TriangleAlert className="h-3.5 w-3.5" />
                {gone.map((g) => g.label).join(", ")} was removed from Settings. Choose another gateway.</p>
            )}
            {live.length > 1 && (
              <ul className="mt-3 flex flex-wrap gap-1.5">
                {routingLines(live).map(({ currency, gateway }) => (
                  <li key={currency} className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs dark:bg-slate-800">
                    <b>{currency}</b><ArrowRight className="h-3 w-3" />{gateway.label}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {p.models.includes("subscription") && (
            <section className="space-y-3" data-panel-plans="">
              <h2 className="text-base font-semibold">Plans</h2>
              <div className="grid gap-3 sm:grid-cols-3">
                {p.plans.map((pl) => (
                  <div key={pl.id} className={`rounded-lg border p-4 ${pl.highlighted ? "border-primary" : ""}`}>
                    <p className="font-medium">{pl.name}</p>
                    <p className="mt-1 text-sm">{Object.entries(pl.prices).map(([c, a]) => price(a, c)).join(" · ")}
                      <span className="text-muted-foreground"> / {pl.interval}</span></p>
                    {pl.trialDays > 0 && <p className="text-xs text-primary">{pl.trialDays}-day free trial</p>}
                    <ul className="mt-2 space-y-1 text-xs text-muted-foreground">{pl.features.map((f) => <li key={f}>✓ {f}</li>)}</ul>
                  </div>
                ))}
              </div>
              <p className="text-sm text-muted-foreground">{p.access === "app" ? "People must hold an active plan to use the app." : "The app stays open; plans add extras."}
                {" "}Subscribers manage their plan at <code>/billing</code> in the app.</p>
            </section>
          )}

          {p.models.includes("one_time") && (
            <section className="flex gap-3 rounded-xl border p-4 text-sm">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              <div>
                <p>One-time payments are taken where a process sends the person to pay (an order's checkout, a booking's deposit).</p>
                <Button variant="link" className="h-auto p-0 text-sm" data-ask-smith-checkout=""
                        onClick={() => askSmith(projectId, "Make sure every process where a person pays for something sends them to checkout, and records the payment when it succeeds.")}>
                  <MessageSquare className="mr-1 h-3.5 w-3.5" />Ask Smith to add or check the checkouts
                </Button>
              </div>
            </section>
          )}

          <section className="space-y-3" data-panel-webhooks="">
            <h2 className="text-base font-semibold">Webhooks</h2>
            <p className="text-sm text-muted-foreground">A webhook is how a gateway tells the published app what happened later — a renewal, a refund, a payment
              finished after the window closed. Payments are confirmed when the payer returns even before a webhook arrives.</p>
            {v.webhooks.length === 0 ? (
              <p className="text-sm">Set up when the app is published — for Stripe and PayPal, Forge registers them itself.</p>
            ) : v.webhooks.map((w) => (
              <div key={`${w.gateway ?? w.provider}-${w.side}`} className="rounded-lg border p-4 text-sm" data-webhook={`${w.provider}:${w.side}`}>
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium">{w.label} · {w.side === "production" ? "Production" : "Test version"}</p>
                  {w.status === "registered" ? <span className="flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-300"><CheckCircle2 className="h-3.5 w-3.5" />Registered by Forge</span>
                    : w.status === "failed" ? <span className="text-xs text-amber-700 dark:text-amber-300">Could not register: {w.detail}</span>
                    : w.status === "stale" ? <span className="text-xs text-amber-700 dark:text-amber-300">Registered again at the next publish</span>
                    : <span className="text-xs text-amber-700 dark:text-amber-300">Paste into {w.label} once</span>}
                </div>
                {w.status === "manual" && w.secretHidden && (
                  <p className="mt-2 text-xs text-muted-foreground">An admin of your organisation pastes this webhook into {w.label} once; its secret is shown to admins only.</p>
                )}
                {w.status === "manual" && w.secret && (
                  <div className="mt-3 space-y-2">
                    <p className="text-xs text-muted-foreground">In Razorpay's dashboard → Webhooks → Add new webhook ({w.side === "production" ? "Live mode" : "Test mode"}): paste the address and secret, tick the events, save.</p>
                    {([["Webhook URL", w.url], ["Secret", w.secret]] as const).map(([k, val]) => (
                      <div key={k} className="flex items-center gap-2">
                        <span className="w-24 shrink-0 text-xs text-muted-foreground">{k}</span>
                        <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1 text-xs">{val}</code>
                        <Button size="icon" variant="ghost" aria-label={`Copy ${k}`} onClick={() => copy(String(val), k)}><Copy className="h-3.5 w-3.5" /></Button>
                      </div>
                    ))}
                    <p className="text-xs"><span className="text-muted-foreground">Events:</span> {(w.events ?? []).join(", ")}</p>
                    <a className="inline-flex items-center gap-1 text-xs text-primary hover:underline" href="https://dashboard.razorpay.com/app/webhooks" target="_blank" rel="noreferrer">
                      Open Razorpay webhooks <ExternalLink className="h-3 w-3" /></a>
                  </div>
                )}
              </div>
            ))}
          </section>
        </>
      )}

      <p className="text-xs text-muted-foreground">Gateways and their keys are your organisation's: <a className="text-primary hover:underline" href={`/org/${orgId}/settings/payments`}>Settings → Payments</a>.</p>

      {editing && (
        <PaymentChoiceDialog projectId={projectId} mode="edit" onClose={() => setEditing(false)}
          onDone={(next: PaymentsView) => {
            setEditing(false);
            toast.success(next.payments.needed ? "Payments saved. The app's preview uses them now." : "Payments turned off.");
          }} />
      )}
    </div>
    </div>
  );
}
