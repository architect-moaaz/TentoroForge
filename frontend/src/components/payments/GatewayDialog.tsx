"use client";

/**
 * Add or edit a payment gateway: which gateway, its test and live keys, and
 * who pays through it. The keys are checked with the gateway on save; a key
 * pasted into the wrong mode is moved to the right one; a refusal is said in
 * the dialog, with everything typed still there.
 */

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Check, ExternalLink, Eye, EyeOff, Info, Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { GatewayMark } from "./GatewayMark";
import {
  COUNTRIES, type Coverage, type Gateway, type GatewayBody, type Mode, type ProviderInfo,
  fieldOfKey, gatewayApi, gatewaysKey, prefixProblem,
} from "@/lib/payment-gateways";

const BEST_FOR: Record<string, string> = {
  razorpay: "Best for taking money in India — UPI, cards, netbanking, wallets and UPI AutoPay for subscriptions.",
  stripe: "Best for customers outside India — cards, Apple Pay and Google Pay in their own currency.",
  paypal: "For buyers who pay with PayPal, worldwide. PayPal does not take INR, AED or SAR.",
};

const COVERAGE_TEXT: Record<Coverage, { title: string; text: string }> = {
  domestic: { title: "Domestic", text: "Payers in its home country" },
  international: { title: "International", text: "Payers in other countries" },
  both: { title: "Both", text: "Anyone, wherever they are" },
};

interface Props {
  orgId: string;
  providers: ProviderInfo[];
  /** Editing this gateway; absent to add one. */
  gateway?: Gateway | null;
  /** Start on this provider's keys (skips the choice). */
  initialProvider?: string | null;
  /** Open on these keys ("Add live keys" opens Live). */
  initialMode?: Mode;
  onClose: () => void;
  onSaved?: (g: Gateway) => void;
}

export function GatewayDialog({ orgId, providers, gateway, initialProvider, initialMode, onClose, onSaved }: Props) {
  const qc = useQueryClient();
  const editing = Boolean(gateway);
  const [providerId, setProviderId] = useState<string | null>(gateway?.provider ?? initialProvider ?? null);
  const provider = providers.find((p) => p.id === providerId);
  const [mode, setMode] = useState<Mode>(initialMode ?? (gateway && !gateway.modes.test.set && gateway.modes.live.set ? "live" : "test"));
  const [keys, setKeys] = useState<Record<Mode, Record<string, string>>>({ test: {}, live: {} });
  const [shown, setShown] = useState<Record<string, boolean>>({});
  const [label, setLabel] = useState(gateway?.label ?? "");
  const [coverage, setCoverage] = useState<Coverage | null>(gateway?.coverage ?? null);
  const [country, setCountry] = useState<string | null>(gateway?.homeCountry ?? null);
  const [currencies, setCurrencies] = useState<string[] | null>(gateway?.currencies ?? null);
  const [makeDefault, setMakeDefault] = useState(false);
  const [clear, setClear] = useState<Mode[]>([]);
  const [problem, setProblem] = useState<string>("");

  const cov: Coverage = coverage ?? provider?.coverage ?? "both";
  const home = country ?? provider?.homeCountry ?? null;
  const cur = currencies ?? provider?.defaultCurrencies ?? [];
  const testName = provider?.testName ?? "Test mode";
  const modeName = (m: Mode) => (m === "test" ? testName : "Live");

  const typed = (m: Mode) => Object.values(keys[m]).some((v) => v.trim());
  const fieldIssues = useMemo(() => {
    const out: Record<string, string> = {};
    if (!provider) return out;
    for (const m of ["test", "live"] as Mode[]) for (const f of provider.fields) {
      const why = prefixProblem(f, m, keys[m][f.key] ?? "", testName);
      if (why) out[`${m}:${f.key}`] = why;
    }
    return out;
  }, [provider, keys, testName]);
  const missing = (m: Mode) => provider ? provider.fields.filter((f) => f.required && !(keys[m][f.key] ?? "").trim()
                                                                && !(editing && gateway?.modes[m].set)) : [];
  // WHY CONNECT IS NOT PRESSABLE, in words: a greyed button and a red star
  // left the owner guessing.
  const blocker = !provider ? "" : Object.keys(fieldIssues).length ? "A key is in the wrong place — see the field marked red."
    : (["test", "live"] as Mode[]).find((m) => typed(m) && missing(m).length)
      ? `Fill in ${missing((["test", "live"] as Mode[]).find((m) => typed(m) && missing(m).length)!).map((f) => f.label).join(" and ")}.`
    : !(editing || typed("test") || typed("live")) ? "Paste at least one set of keys — test or live."
    : cur.length === 0 ? "Choose at least one currency."
    : cov === "domestic" && !home ? "Choose the home country of a domestic gateway." : "";
  const ready = Boolean(provider) && !blocker;

  const save = useMutation({
    mutationFn: async () => {
      const body: GatewayBody = {
        label: label.trim() || provider!.name, coverage: cov, homeCountry: home, currencies: cur,
        ...(makeDefault ? { isDefault: true } : {}),
        ...(typed("test") ? { test: keys.test } : {}), ...(typed("live") ? { live: keys.live } : {}),
        ...(clear.length ? { clear } : {}),
      };
      return editing ? gatewayApi.edit(orgId, gateway!.id, body) : gatewayApi.create(orgId, { provider: provider!.id, ...body });
    },
    onSuccess: (g) => {
      qc.invalidateQueries({ queryKey: gatewaysKey(orgId) });
      const verified = (["live", "test"] as Mode[]).find((m) => g.modes[m].check?.ok);
      const who = verified ? g.modes[verified].check?.account : "";
      toast.success(verified
        ? `${g.label} ${editing ? "saved" : "is connected"} — ${modeName(verified).toLowerCase()} keys verified${who ? ` for ${who}` : ""}.`
        : `${g.label} is saved. ${g.status === "unchecked" ? "Its keys could not be checked yet; Forge will check them again." : ""}`);
      onSaved?.(g);
      onClose();
    },
    onError: (err: unknown) => setProblem(err instanceof Error ? err.message : "The gateway could not be saved."),
  });

  const setKey = (m: Mode, key: string, value: string) => {
    setProblem("");
    // Keys typed into a mode marked for removal replace it instead (the server
    // used to drop them and keep the removal).
    if (value.trim()) setClear((c) => c.filter((x) => x !== m));
    setKeys((k) => ({ ...k, [m]: { ...k[m], [key]: value } }));
  };
  // A KEY PASTED INTO THE WRONG PLACE GOES TO THE RIGHT ONE: its prefix says
  // which field, and which mode — a live key under Test, a Key ID where the
  // secret goes. Only on a paste: a key typed by hand would be moved
  // half-typed; typing gets the field's own "this is a live key" line instead.
  const onPaste = (m: Mode, key: string) => (e: React.ClipboardEvent<HTMLInputElement>) => {
    const value = e.clipboardData.getData("text").trim();
    const belongs = fieldOfKey(provider, value);
    if (!belongs || (belongs.mode === m && belongs.field.key === key) || (keys[belongs.mode][belongs.field.key] ?? "").trim()) return;
    e.preventDefault();
    setProblem("");
    setClear((c) => c.filter((x) => x !== belongs.mode));
    setKeys((k) => ({ ...k, [belongs.mode]: { ...k[belongs.mode], [belongs.field.key]: value } }));
    setMode(belongs.mode);
    toast.info(belongs.field.key !== key
      ? `That is the ${belongs.field.label} — it is in ${belongs.field.label}${belongs.mode !== m ? ` under ${modeName(belongs.mode)}` : ""} now.`
      : `That is a ${belongs.mode === "live" ? "live" : testName.toLowerCase()} key — it is under ${modeName(belongs.mode)} now.`);
  };
  // Another gateway chosen: nothing typed for the first one comes along (its
  // currencies, its name, its keys would be refused by the next).
  const chooseAnother = () => {
    setProviderId(null); setProblem(""); setKeys({ test: {}, live: {} }); setShown({}); setLabel("");
    setCoverage(null); setCountry(null); setCurrencies(null); setMakeDefault(false); setClear([]); setMode("test");
  };

  // --- Step 1: which gateway --------------------------------------------- //
  if (!provider) {
    return (
      <Dialog open onOpenChange={(o) => !o && onClose()}>
        <DialogContent data-gateway-dialog="choose" className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add a payment gateway</DialogTitle>
            <DialogDescription>
              Which account should your apps take money through? You can add as many as your business uses — one for India and
              one for everyone else is common — and choose per app which ones it uses.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            {providers.map((p) => (
              <button key={p.id} type="button" data-choose-provider={p.id} onClick={() => setProviderId(p.id)}
                      className="flex items-start gap-4 rounded-xl border border-slate-200 p-4 text-left transition hover:border-primary hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary dark:border-slate-800 dark:hover:bg-slate-900">
                <GatewayMark provider={p.id} size={44} />
                <span className="flex-1">
                  <span className="block text-[15px] font-semibold">{p.name}</span>
                  <span className="mt-0.5 block text-sm text-muted-foreground">{BEST_FOR[p.id] ?? p.tagline}</span>
                  <span className="mt-2 block text-xs text-muted-foreground">{p.paymentMethods} · {p.currencies.slice(0, 6).join(", ")}{p.currencies.length > 6 ? "…" : ""}</span>
                </span>
              </button>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  // --- Step 2: keys and who pays through it ------------------------------ //
  const saved = (m: Mode) => editing && gateway!.modes[m].set && !clear.includes(m);
  return (
    <Dialog open onOpenChange={(o) => !o && !save.isPending && onClose()}>
      <DialogContent data-gateway-dialog={provider.id} className="max-h-[92vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-3">
            <GatewayMark provider={provider.id} size={32} />
            {editing ? `Edit ${gateway!.label}` : `Connect ${provider.name}`}
          </DialogTitle>
          <DialogDescription>{provider.tagline}</DialogDescription>
        </DialogHeader>

        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Keys</h3>
            {provider.keysUrl[mode] && (
              <a href={provider.keysUrl[mode]} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                Where to find your {modeName(mode).toLowerCase()} keys <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
          <div role="tablist" aria-label="Key mode" className="inline-flex rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
            {(["test", "live"] as Mode[]).map((m) => (
              <button key={m} role="tab" type="button" aria-selected={mode === m} data-mode-tab={m} onClick={() => setMode(m)}
                      className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition ${mode === m ? "bg-white shadow-sm dark:bg-slate-950" : "text-muted-foreground hover:text-foreground"}`}>
                {modeName(m)}
                {(saved(m) || (typed(m) && missing(m).length === 0 && !Object.keys(fieldIssues).some((k) => k.startsWith(`${m}:`))))
                  && <Check className="h-3.5 w-3.5 text-emerald-600" />}
              </button>
            ))}
          </div>
          <p className="flex gap-2 rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-muted-foreground dark:bg-slate-900">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {mode === "test"
              ? `${testName} keys run your apps' previews and test version. Nobody is charged — use the gateway's test cards and UPI ids.`
              : "Live keys are used only by your apps in production, where real money moves. They never reach a preview or the test version."}
          </p>
          {saved(mode) && (
            <div className="flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2 text-xs text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200">
              <span className="flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5" />
                {modeName(mode)} keys saved{gateway!.modes[mode].masked ? `: ${Object.values(gateway!.modes[mode].masked!).join(" · ")}` : ""}. Type a field only to change it.
              </span>
              {gateway!.modes[mode === "test" ? "live" : "test"].set && (
                <button type="button" className="font-medium underline" data-clear-mode={mode}
                        onClick={() => setClear((c) => [...c, mode])}>Remove</button>
              )}
            </div>
          )}
          {clear.includes(mode) && (
            <p className="text-xs text-amber-700 dark:text-amber-300">The {modeName(mode).toLowerCase()} keys will be removed when you save.
              <button type="button" className="ml-2 underline" onClick={() => setClear((c) => c.filter((x) => x !== mode))}>Keep them</button></p>
          )}
          <div className="space-y-4">
            {provider.fields.map((f) => {
              const id = `gw-${mode}-${f.key}`;
              const issue = fieldIssues[`${mode}:${f.key}`];
              const hidden = f.secret && !shown[id];
              return (
                <div key={id} className="space-y-1.5">
                  <Label htmlFor={id} className="text-sm">
                    {f.label}{f.required && !saved(mode) && <span className="ml-0.5 text-red-500">*</span>}
                    {!f.required && <span className="ml-1 text-xs font-normal text-muted-foreground">optional</span>}
                  </Label>
                  <div className="relative">
                    <Input id={id} data-key-field={`${mode}:${f.key}`} autoComplete="off" spellCheck={false}
                           type={hidden ? "password" : "text"} value={keys[mode][f.key] ?? ""}
                           onChange={(e) => setKey(mode, f.key, e.target.value)} onPaste={onPaste(mode, f.key)}
                           placeholder={saved(mode) ? "Saved — leave empty to keep" : (f.prefix[mode]?.[0] ? `${f.prefix[mode]![0]}…` : "")}
                           aria-invalid={Boolean(issue)} className={`pr-10 font-mono text-[13px] ${issue ? "border-red-400 focus-visible:ring-red-400" : ""}`} />
                    {f.secret && (
                      <button type="button" aria-label={`${hidden ? "Show" : "Hide"} ${f.label}`} onClick={() => setShown((s) => ({ ...s, [id]: !s[id] }))}
                              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                        {hidden ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                      </button>
                    )}
                  </div>
                  {issue ? <p className="text-xs text-red-600" data-field-issue="">{issue}</p>
                         : f.help && <p className="text-xs text-muted-foreground">{f.help}</p>}
                </div>
              );
            })}
          </div>
          {!editing && !typed("live") && mode === "test" && (
            <p className="text-xs text-muted-foreground">Live keys can be added now or later — the gateway works in test until they are.</p>
          )}
        </section>

        <section className="space-y-4 border-t pt-5">
          <h3 className="text-sm font-semibold">Who pays through it</h3>
          <div className="space-y-1.5">
            <Label htmlFor="gw-label">Name</Label>
            <Input id="gw-label" data-gateway-label="" value={label} maxLength={80} placeholder={`${provider.name}${provider.homeCountry ? ` ${COUNTRIES.find((c) => c.code === provider.homeCountry)?.name ?? ""}` : ""}`}
                   onChange={(e) => setLabel(e.target.value)} />
            <p className="text-xs text-muted-foreground">How you will tell it apart from other gateways, e.g. “Razorpay India” or “Stripe US”.</p>
          </div>
          <div className="space-y-1.5">
            <Label id="gw-coverage-label">Takes money from</Label>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3" role="radiogroup" aria-labelledby="gw-coverage-label">
              {(Object.keys(COVERAGE_TEXT) as Coverage[]).map((c) => (
                <button key={c} type="button" role="radio" aria-checked={cov === c} data-coverage={c} onClick={() => setCoverage(c)}
                        className={`rounded-lg border p-2.5 text-left text-sm transition ${cov === c ? "border-primary bg-primary/5 ring-1 ring-primary" : "border-slate-200 hover:border-slate-300 dark:border-slate-800"}`}>
                  <span className="block font-medium">{COVERAGE_TEXT[c].title}</span>
                  <span className="block text-xs text-muted-foreground">{COVERAGE_TEXT[c].text}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gw-home-country">Home country {cov === "domestic" && <span className="text-red-500">*</span>}</Label>
            <Select value={home || "none"} onValueChange={(v) => setCountry(v === "none" ? "" : v)}>
              <SelectTrigger id="gw-home-country" data-home-country="" className="w-full"><SelectValue placeholder="Choose a country" /></SelectTrigger>
              <SelectContent>
                {cov !== "domestic" && <SelectItem value="none">No home country</SelectItem>}
                {COUNTRIES.map((c) => <SelectItem key={c.code} value={c.code}>{c.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">Payers in this country are sent here first, when it is a domestic gateway.</p>
          </div>
          <div className="space-y-1.5">
            <Label id="gw-currencies-label">Currencies</Label>
            <div className="flex flex-wrap gap-1.5" data-currencies="" role="group" aria-labelledby="gw-currencies-label">
              {provider.currencies.map((c) => {
                const on = cur.includes(c);
                return (
                  <button key={c} type="button" aria-pressed={on} data-currency={c}
                          onClick={() => setCurrencies(on ? cur.filter((x) => x !== c) : [...cur, c])}
                          className={`rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition ${on ? "bg-primary text-primary-foreground ring-primary" : "ring-slate-300 text-slate-600 hover:ring-slate-400 dark:ring-slate-700 dark:text-slate-300"}`}>
                    {c}
                  </button>
                );
              })}
            </div>
            {cur.length === 0 && <p className="text-xs text-red-600">Choose at least one currency.</p>}
            {provider.id === "razorpay" && cur.some((c) => c !== "INR") && (
              <p className="text-xs text-amber-700 dark:text-amber-300">Currencies other than INR need international payments switched on in your Razorpay dashboard.</p>
            )}
          </div>
          {!(editing && gateway!.isDefault) && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" data-make-default="" checked={makeDefault} onChange={(e) => setMakeDefault(e.target.checked)} className="h-4 w-4 rounded border-slate-300" />
              Make this the default gateway for new apps
            </label>
          )}
          <p className="flex gap-2 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {provider.webhooks === "auto"
              ? `Keys are encrypted and never shown again. When an app goes live, Forge registers its webhook with ${provider.name} for you.`
              : `Keys are encrypted and never shown again. When an app goes live, Forge gives you its webhook address and secret to paste into ${provider.name} once.`}
          </p>
        </section>

        {problem && (
          <div role="alert" data-gateway-problem="" className="flex gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {problem}
          </div>
        )}

        <DialogFooter className="gap-2 sm:justify-between">
          {!editing ? (
            <Button variant="ghost" onClick={chooseAnother} disabled={save.isPending}>Choose another gateway</Button>
          ) : <span />}
          <div className="flex flex-wrap items-center justify-end gap-2">
            {blocker && !problem && <p className="w-full text-right text-xs text-muted-foreground sm:w-auto" data-gateway-blocker="">{blocker}</p>}
            <Button variant="outline" onClick={onClose} disabled={save.isPending}>Cancel</Button>
            <Button data-gateway-save="" onClick={() => save.mutate()} disabled={!ready || save.isPending}>
              {save.isPending ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Checking with {provider.name}…</> : editing ? "Check and save" : "Connect"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
