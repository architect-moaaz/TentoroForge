"use client";

/**
 * How an app takes money — asked when it is about to be built (and from its
 * Payments panel any time after). Forge has already worked out whether it
 * takes money and why; the owner confirms what it sells, ticks which of the
 * organisation's gateways it uses (the best ones are ticked already), sees
 * which payers go where, and, for subscriptions, edits the plans.
 *
 * Spec: docs/PAYMENT-GATEWAYS-PLAN.md.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Check, ExternalLink, Loader2, Plus, Sparkles, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { GatewayMark } from "./GatewayMark";
import { STATUS_WORDS, type Gateway, coverageWords, routingLines, suggested } from "@/lib/payment-gateways";

export type Model = "one_time" | "subscription";

export interface Plan {
  id: string;
  name: string;
  description?: string;
  interval: "day" | "week" | "month" | "year";
  intervalCount: number;
  prices: Record<string, number>;
  trialDays: number;
  features: string[];
  highlighted?: boolean;
}

export interface AppPayments {
  needed: boolean | null;
  models: Model[];
  reason: string;
  decidedBy: "forge" | "person" | "smith" | null;
  gateways: Array<{ gateway: string; provider: string; label: string; currencies: string[] }>;
  plans: Plan[];
  access: "app" | "none";
  currency: string;
  decided: boolean;
}

export interface PaymentsView {
  payments: AppPayments;
  gateways: Gateway[];
  canManageGateways: boolean;
  webhooks: Array<{ provider: string; gateway?: string; label: string; side: string; url: string; status: string; detail?: string; secret?: string;
    secretHidden?: boolean; events?: string[] }>;
  /** Whether the published app can take money: each chosen gateway's live keys. */
  readiness?: { needed: boolean; liveReady: boolean; gateways: ReadinessLine[]; missing: ReadinessLine[] };
  orgId: string;
}

export interface ReadinessLine { gateway: string; label: string; provider: string; live: boolean; removed: boolean; state: string; currencies: string[] }

/** Decimals a price may carry in each currency (the gateways' own lists). */
const ZERO_DECIMAL = new Set(["BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"]);
const THREE_DECIMAL = new Set(["BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"]);
export const decimalsOf = (c: string) => (ZERO_DECIMAL.has(c) ? 0 : THREE_DECIMAL.has(c) ? 3 : 2);

/** A typed price: its number, or why it cannot be charged (empty is no price in that currency). */
export function readPrice(text: string, currency: string): { value: number | null; problem: string } {
  const t = text.trim();
  if (!t) return { value: null, problem: "" };
  const n = Number(t);
  if (!Number.isFinite(n)) return { value: null, problem: `is not a number` };
  if (n <= 0) return { value: null, problem: `must be more than zero` };
  const places = decimalsOf(currency);
  if (Math.round(n * 10 ** places) / 10 ** places !== n) return { value: null, problem: places ? `has more than ${places} decimals` : "has no decimals in " + currency };
  return { value: n, problem: "" };
}

export const paymentsKey = (projectId: string) => ["appPayments", projectId] as const;

/** Smith's chip that opens this dialog (the platform's `app_payments.PAYMENT_CHIP`); never sent as words. */
export const PAYMENT_CHIP = "Choose payment gateways";

export const paymentsApi = {
  get: (projectId: string) => api.get<PaymentsView>(`/api/projects/${projectId}/payments`),
  decide: (projectId: string) => api.post<PaymentsView>(`/api/projects/${projectId}/payments/decide`),
  choose: (projectId: string, body: { needed: boolean; gateways: string[]; models?: Model[]; plans?: Plan[]; access?: "app" | "none" }) =>
    api.put<PaymentsView>(`/api/projects/${projectId}/payments`, body),
};

const MODEL_TEXT: Record<Model, { title: string; text: string }> = {
  one_time: { title: "One-time payments", text: "Orders, bookings, fees, tickets, donations" },
  subscription: { title: "Subscriptions", text: "Memberships and plans renewed every month or year" },
};

let planSeq = 0;
const newPlan = (currency: string): Plan => ({
  id: `plan-${Date.now().toString(36)}-${planSeq++}`, name: "", interval: "month", intervalCount: 1, prices: { [currency]: 0 },
  trialDays: 0, features: [],
});

interface Props {
  projectId: string;
  appName?: string;
  /** "build": asked as the build starts (its buttons build); "edit": from the Payments panel. */
  mode: "build" | "edit";
  onClose: () => void;
  /** After a choice is saved. In build mode, the caller starts the build. */
  onDone: (view: PaymentsView) => void;
}

export function PaymentChoiceDialog({ projectId, appName, mode, onClose, onDone }: Props) {
  const qc = useQueryClient();
  // In build mode Forge decides first (once per definition; a person's choice
  // is kept); after that the dialog only reads — coming back from Settings
  // re-reads the gateways, it does not decide again.
  const decided = useRef(false);
  const view = useQuery({
    queryKey: [...paymentsKey(projectId), mode],
    queryFn: async () => {
      if (mode === "build" && !decided.current) {
        const v = await paymentsApi.decide(projectId);
        decided.current = true;
        return v;
      }
      return paymentsApi.get(projectId);
    },
    refetchOnWindowFocus: "always",
    retry: 0,
  });
  const data = view.data;
  const p = data?.payments;
  const gateways = useMemo(() => data?.gateways ?? [], [data]);
  const [models, setModels] = useState<Model[] | null>(null);
  const [picked, setPicked] = useState<string[] | null>(null);
  const [plans, setPlans] = useState<Plan[] | null>(null);
  // Prices as typed ("plan id:currency" -> text): a number box that rewrote
  // "" to 0 could not be cleared, and a −5 was dropped without a word.
  const [priceText, setPriceText] = useState<Record<string, string>>({});
  const [access, setAccess] = useState<"app" | "none" | null>(null);
  const [problem, setProblem] = useState("");

  // Fill from what Forge decided, once it has.
  useEffect(() => {
    if (!p) return;
    setModels((m) => m ?? (p.models.length ? p.models : ["one_time"]));
    setPlans((x) => x ?? p.plans);
    setAccess((a) => a ?? p.access);
  }, [p]);
  // A gateway set up in another tab arrives on focus: tick the best ones when
  // nothing is ticked yet. What the owner chose stays chosen — "test payments"
  // (none) too — and a gateway whose keys were refused is never ticked for them.
  useEffect(() => {
    if (!p || picked !== null || !gateways.length) return;
    const chosen = p.gateways.map((g) => g.gateway)
      .filter((id) => gateways.some((g) => g.id === id && g.status !== "attention"));
    const ownChoice = p.decidedBy === "person" || p.decidedBy === "smith";
    setPicked(chosen.length || (ownChoice && p.needed) ? chosen : suggested(gateways, p.currency).map((g) => g.id));
  }, [p, gateways, picked]);

  const ms = models ?? [];
  const sel = (picked ?? []).map((id) => gateways.find((g) => g.id === id)).filter(Boolean) as Gateway[];
  const covered = new Set(sel.flatMap((g) => g.currencies));
  const currency = p?.currency ?? "USD";
  const planList = plans ?? [];
  // The text of a price box: what was typed, else the plan's own price.
  const textOf = (pl: Plan, c: string) => priceText[`${pl.id}:${c}`] ?? (pl.prices[c] != null && pl.prices[c] > 0 ? String(pl.prices[c]) : "");
  // Every currency the gateways take, and every currency a plan is already
  // priced in — a price never hides behind a currency the list left out.
  const priceCurrencies = useMemo(() => {
    const priced = planList.flatMap((pl) => Object.keys(pl.prices).filter((c) => (pl.prices[c] ?? 0) > 0));
    const list = [currency, ...Array.from(covered), ...priced];
    return Array.from(new Set(sel.length ? list : [currency, ...priced]));
  }, [currency, covered, sel.length, planList]);

  const warnings: string[] = [];
  if (!ms.length) warnings.push("Choose what it sells — one-time payments, subscriptions or both.");
  // As the server: only one-time payments are priced in the app's own currency.
  if (sel.length && ms.includes("one_time") && !covered.has(currency))
    warnings.push(`One-time payments are in ${currency}, and none of these gateways takes ${currency}.`);
  if (ms.includes("subscription")) {
    if (!planList.length) warnings.push("Add at least one plan.");
    for (const pl of planList) {
      const name = pl.name.trim() || "A plan";
      if (!pl.name.trim()) warnings.push("Every plan needs a name.");
      let priced = false;
      for (const c of priceCurrencies) {
        const { value, problem: why } = readPrice(textOf(pl, c), c);
        if (why) warnings.push(`${name}'s price in ${c} ${why}.`);
        if (value != null) {
          priced = true;
          if (sel.length && !covered.has(c)) warnings.push(`${name} is priced in ${c}, which none of the chosen gateways takes.`);
        }
      }
      if (!priced) warnings.push(`${name} needs a price.`);
    }
  }
  const blocking = warnings.length > 0;

  const save = useMutation({
    // The gateways as shown: one removed in another tab is not sent.
    mutationFn: (needed: boolean) => paymentsApi.choose(projectId, needed
      ? { needed: true, gateways: sel.map((g) => g.id), models: ms,
          plans: ms.includes("subscription") ? planList.map((pl) => ({ ...pl,
            prices: Object.fromEntries(priceCurrencies.map((c) => [c, readPrice(textOf(pl, c), c).value]).filter(([, v]) => v != null)),
            features: pl.features.map((f) => f.trim()).filter(Boolean) })) : [],
          access: access ?? "none" }
      : { needed: false, gateways: [] }),
    onSuccess: (v) => { qc.setQueryData(paymentsKey(projectId), v); qc.invalidateQueries({ queryKey: paymentsKey(projectId) }); onDone(v); },
    onError: (e: unknown) => setProblem(e instanceof Error ? e.message : "It could not be saved."),
  });

  const toggleGateway = (g: Gateway) => {
    setProblem("");
    setPicked((cur) => {
      const now = cur ?? [];
      if (now.includes(g.id)) return now.filter((x) => x !== g.id);
      // One account per gateway for an app: picking a second Stripe replaces the first.
      return [...now.filter((x) => gateways.find((o) => o.id === x)?.provider !== g.provider), g.id];
    });
  };
  const setPlan = (i: number, patch: Partial<Plan>) => setPlans((cur) => (cur ?? []).map((pl, j) => (j === i ? { ...pl, ...patch } : pl)));

  const settingsHref = data ? `/org/${data.orgId}/settings/payments` : "#";
  const title = mode === "build" ? `How should ${appName || "this app"} take payments?` : "Payments";

  return (
    <Dialog open onOpenChange={(o) => !o && !save.isPending && onClose()}>
      <DialogContent data-payment-choice={mode} className="max-h-[92vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {mode === "build" ? "Choose before the build starts — you can change it any time from the app's Payments panel."
                              : "How this app takes money, through which of your gateways, and what it sells."}
          </DialogDescription>
        </DialogHeader>

        {view.isError && !p ? (
          // NOTHING TO SHOW IS SAID, with a way on: an error used to spin here for good.
          <div className="space-y-3 py-6 text-sm" role="alert" data-payment-load-error="">
            <p className="text-red-700 dark:text-red-300">{(view.error as Error)?.message || "How this app takes money could not be read."}</p>
            <Button variant="outline" size="sm" onClick={() => void view.refetch()}>Try again</Button>
          </div>
        ) : view.isLoading || !p ? (
          <div className="flex items-center gap-3 py-10 text-sm text-muted-foreground" data-payment-deciding="">
            <Loader2 className="h-4 w-4 animate-spin" /> Working out how this app takes money…
          </div>
        ) : (
          <div className="space-y-6">
            {view.isError && (
              <p className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                The latest gateways could not be read; this shows what was read before.</p>
            )}
            {p.reason && (
              <p className="flex gap-2 rounded-lg bg-primary/5 p-3 text-sm" data-payment-reason="">
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <span><b>{p.decidedBy === "person" ? "Your choice" : "Forge noticed"}:</b> {p.reason}</span>
              </p>
            )}

            <section className="space-y-2">
              <h3 className="text-sm font-semibold">What it sells</h3>
              <div className="grid grid-cols-2 gap-2">
                {(Object.keys(MODEL_TEXT) as Model[]).map((m) => {
                  const on = ms.includes(m);
                  return (
                    <button key={m} type="button" aria-pressed={on} data-model={m}
                            onClick={() => { setProblem(""); setModels(on ? ms.filter((x) => x !== m) : [...ms, m]);
                              if (m === "subscription" && !on && !planList.length) setPlans([{ ...newPlan(currency), name: "Monthly", highlighted: true }]); }}
                            className={`flex items-start gap-2 rounded-lg border p-3 text-left text-sm transition ${on ? "border-primary bg-primary/5 ring-1 ring-primary" : "border-slate-200 hover:border-slate-300 dark:border-slate-800"}`}>
                      <span className={`mt-0.5 grid h-4 w-4 place-items-center rounded border ${on ? "border-primary bg-primary text-primary-foreground" : "border-slate-300 dark:border-slate-600"}`}>{on && <Check className="h-3 w-3" />}</span>
                      <span><span className="block font-medium">{MODEL_TEXT[m].title}</span><span className="block text-xs text-muted-foreground">{MODEL_TEXT[m].text}</span></span>
                    </button>
                  );
                })}
              </div>
            </section>

            <section className="space-y-2">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">Paid through</h3>
                <a href={settingsHref} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-primary hover:underline" data-manage-gateways="">
                  {gateways.length ? "Add or edit gateways" : "Set up a gateway"} <ExternalLink className="h-3 w-3" />
                </a>
              </div>
              {gateways.length === 0 ? (
                <div className="rounded-lg border border-dashed p-4 text-sm" data-no-gateways="">
                  <p className="font-medium">No payment gateway is connected yet.</p>
                  <p className="mt-1 text-muted-foreground">
                    {data?.canManageGateways ? "Connect Razorpay, Stripe or PayPal in Settings → Payments (it opens in a new tab; come back and it appears here)."
                                             : "Ask an admin of your organisation to connect one in Settings → Payments."}{" "}
                    Or build now: the app uses a test checkout that charges nobody until a gateway is chosen.
                  </p>
                </div>
              ) : (
                <div className="grid gap-2">
                  {gateways.map((g) => {
                    const on = (picked ?? []).includes(g.id);
                    const broken = g.status === "attention";
                    return (
                      // A refused gateway cannot be ticked — but one ticked before can be unticked.
                      <button key={g.id} type="button" disabled={broken && !on} aria-pressed={on} data-choose-gateway={g.id} onClick={() => toggleGateway(g)}
                              className={`flex items-center gap-3 rounded-lg border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-60 ${on ? "border-primary bg-primary/5 ring-1 ring-primary" : "border-slate-200 hover:border-slate-300 dark:border-slate-800"}`}>
                        <span className={`grid h-4 w-4 shrink-0 place-items-center rounded border ${on ? "border-primary bg-primary text-primary-foreground" : "border-slate-300 dark:border-slate-600"}`}>{on && <Check className="h-3 w-3" />}</span>
                        <GatewayMark provider={g.provider} size={32} />
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium">{g.label}{g.isDefault && <span className="ml-1.5 text-xs font-normal text-muted-foreground">default</span>}</span>
                          <span className="block truncate text-xs text-muted-foreground">{coverageWords(g)} · {g.currencies.join(", ")}</span>
                        </span>
                        <span className={`shrink-0 text-xs ${broken ? "text-amber-700 dark:text-amber-300" : g.status === "ready" ? "text-emerald-700 dark:text-emerald-300" : "text-muted-foreground"}`}>
                          {broken ? (on ? "Keys refused — untick it or fix its keys" : "Fix its keys first") : STATUS_WORDS[g.status]}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
              {sel.length > 1 && (
                <ul className="flex flex-wrap gap-1.5 pt-1" data-routing-preview="">
                  {routingLines(sel).map(({ currency: c, gateway }) => (
                    <li key={c} className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs dark:bg-slate-800">
                      <b>{c}</b><ArrowRight className="h-3 w-3" />{gateway.label}
                    </li>
                  ))}
                </ul>
              )}
              {sel.length > 0 && sel.every((g) => g.status === "test_only") && (
                <p className="text-xs text-muted-foreground">Only test keys are set: the app takes test payments until live keys are added in Settings.</p>
              )}
            </section>

            {ms.includes("subscription") && (
              <section className="space-y-3" data-plans="">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold">Plans</h3>
                  {planList.length < 8 && (
                    <Button type="button" variant="ghost" size="sm" data-add-plan="" onClick={() => setPlans([...planList, newPlan(currency)])}>
                      <Plus className="mr-1 h-4 w-4" />Add a plan
                    </Button>
                  )}
                </div>
                {planList.map((pl, i) => (
                  <div key={pl.id} data-plan={i} className="space-y-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                    <div className="flex flex-wrap gap-2 sm:flex-nowrap">
                      <div className="min-w-0 flex-1 space-y-1">
                        <Label htmlFor={`plan-name-${i}`} className="text-xs">Name</Label>
                        <Input id={`plan-name-${i}`} value={pl.name} maxLength={60} placeholder="Pro" onChange={(e) => setPlan(i, { name: e.target.value })} />
                      </div>
                      <div className="w-36 space-y-1">
                        <Label htmlFor={`plan-interval-${i}`} className="text-xs">Billed</Label>
                        <select id={`plan-interval-${i}`} value={`${pl.interval}`} onChange={(e) => setPlan(i, { interval: e.target.value as Plan["interval"], intervalCount: 1 })}
                                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm" data-plan-interval={i}>
                          <option value="month">Every month</option>
                          <option value="year">Every year</option>
                          <option value="week">Every week</option>
                          <option value="day">Every day</option>
                        </select>
                      </div>
                      <Button type="button" variant="ghost" size="icon" className="mt-5" aria-label={`Remove plan ${pl.name || i + 1}`} onClick={() => setPlans(planList.filter((_, j) => j !== i))}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {priceCurrencies.map((c) => {
                        const id = `plan-price-${i}-${c}`;
                        const why = readPrice(textOf(pl, c), c).problem;
                        return (
                          <div key={c} className="w-32 space-y-1">
                            <Label htmlFor={id} className="text-xs">Price in {c}{c !== currency && <span className="text-muted-foreground"> (optional)</span>}</Label>
                            <Input id={id} type="text" inputMode="decimal" data-plan-price={`${i}:${c}`} value={textOf(pl, c)} aria-invalid={Boolean(why)}
                                   aria-label={`${pl.name || "Plan"} price in ${c}`} placeholder={decimalsOf(c) ? "0." + "0".repeat(decimalsOf(c)) : "0"}
                                   className={why ? "border-red-400 focus-visible:ring-red-400" : ""}
                                   onChange={(e) => { setProblem(""); setPriceText((t) => ({ ...t, [`${pl.id}:${c}`]: e.target.value })); }} />
                          </div>
                        );
                      })}
                      <div className="w-28 space-y-1">
                        <Label htmlFor={`plan-trial-${i}`} className="text-xs">Free trial (days)</Label>
                        <Input id={`plan-trial-${i}`} type="number" min={0} max={365} value={pl.trialDays || ""} placeholder="0"
                               onChange={(e) => setPlan(i, { trialDays: Math.max(0, Math.min(365, Number(e.target.value) || 0)) })} />
                      </div>
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor={`plan-features-${i}`} className="text-xs">What it includes (one per line)</Label>
                      <textarea id={`plan-features-${i}`} rows={2} value={pl.features.join("\n")} onChange={(e) => setPlan(i, { features: e.target.value.split("\n") })}
                                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder={"Unlimited bookings\nPriority support"} />
                    </div>
                  </div>
                ))}
                <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Access">
                  {([["app", "Members must subscribe", "The app opens only for people with an active plan."],
                     ["none", "The app stays open", "Plans add extras; nothing is locked."]] as const).map(([v, t, d]) => (
                    <button key={v} type="button" role="radio" aria-checked={(access ?? "none") === v} data-access={v} onClick={() => setAccess(v)}
                            className={`rounded-lg border p-2.5 text-left text-sm ${(access ?? "none") === v ? "border-primary bg-primary/5 ring-1 ring-primary" : "border-slate-200 dark:border-slate-800"}`}>
                      <span className="block font-medium">{t}</span><span className="block text-xs text-muted-foreground">{d}</span>
                    </button>
                  ))}
                </div>
              </section>
            )}

            {(warnings.length > 0 || problem) && (
              <div role="alert" data-payment-problem="" className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <ul className="space-y-0.5">{Array.from(new Set([problem, ...warnings].filter(Boolean))).map((w) => <li key={w}>{w}</li>)}</ul>
              </div>
            )}
          </div>
        )}

        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="ghost" data-payments-none="" onClick={() => save.mutate(false)} disabled={save.isPending || (!p && !view.isError)}>
            {mode === "build" ? "Build without payments" : "Turn payments off"}
          </Button>
          <Button data-payments-save="" onClick={() => save.mutate(true)} disabled={save.isPending || !p || blocking}>
            {save.isPending ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Saving…</>
              : mode === "build" ? (sel.length ? "Use these and build" : "Build with test payments") : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
