"use client";

/**
 * /org/[orgId]/settings/payments — the accounts the organisation's apps take
 * money through.
 *
 * Each gateway is a card that says in a glance whether it can take real
 * money, who it was verified for and when, who pays through it and in which
 * currencies. Above the cards, how a payer is routed when an app uses all of
 * them. Keys are added in a dialog and checked with the gateway on save.
 *
 * Spec: docs/PAYMENT-GATEWAYS-PLAN.md.
 */

import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle, ArrowRight, CheckCircle2, CircleDashed, CreditCard, Loader2, MoreHorizontal, Plus, RefreshCw, Route, Star, Trash2, Pencil,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { GatewayDialog } from "@/components/payments/GatewayDialog";
import { GatewayMark } from "@/components/payments/GatewayMark";
import {
  STATUS_WORDS, type Gateway, type GatewayStatus, type Mode, coverageWords, gatewayApi, gatewaysKey, routingLines, timeAgo,
} from "@/lib/payment-gateways";

const STATUS_STYLE: Record<GatewayStatus, string> = {
  ready: "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-950/40 dark:text-emerald-300",
  test_only: "bg-sky-50 text-sky-700 ring-sky-600/20 dark:bg-sky-950/40 dark:text-sky-300",
  unchecked: "bg-slate-100 text-slate-600 ring-slate-500/20 dark:bg-slate-800 dark:text-slate-300",
  attention: "bg-amber-50 text-amber-800 ring-amber-600/20 dark:bg-amber-950/40 dark:text-amber-300",
};

export default function PaymentsSettingsPage({ params }: { params: Promise<{ orgId: string }> }) {
  const { orgId } = use(params);
  return <PaymentsSettings orgId={orgId} />;
}

function PaymentsSettings({ orgId }: { orgId: string }) {
  const providers = useQuery({ queryKey: ["paymentProviders"], queryFn: gatewayApi.providers, staleTime: 3_600_000 });
  const list = useQuery({ queryKey: gatewaysKey(orgId), queryFn: () => gatewayApi.list(orgId) });
  const [dialog, setDialog] = useState<{ gateway?: Gateway | null; provider?: string | null; mode?: Mode } | null>(null);
  const [removing, setRemoving] = useState<Gateway | null>(null);
  const gateways = list.data?.gateways ?? [];
  const canManage = Boolean(list.data?.canManage);

  if (list.isLoading || providers.isLoading) {
    return <div className="p-8"><h1 className="mb-2 text-2xl font-semibold">Payments</h1><p className="text-muted-foreground">Loading…</p></div>;
  }
  if (list.isError || providers.isError) {
    // Without the gateways' own descriptions nothing here can be added or
    // changed: said, with a way to try again, not buttons that do nothing.
    return <div className="p-8"><h1 className="mb-2 text-2xl font-semibold">Payments</h1>
      <p className="text-red-600 dark:text-red-400" role="alert">
        {list.isError ? `The gateways could not be loaded: ${(list.error as Error)?.message}` : "The payment gateways Forge supports could not be loaded."}</p>
      <Button variant="outline" className="mt-3" onClick={() => { void list.refetch(); void providers.refetch(); }}>Try again</Button></div>;
  }

  return (
    <div className="p-8" data-payments-settings="">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight"><CreditCard className="h-6 w-6" /> Payments</h1>
          <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">
            The gateways your apps take money through. When Forge builds an app that sells something or offers a subscription, it asks
            which of these to use. Test keys run previews and the test version; live keys are used only in production.
          </p>
        </div>
        {canManage && gateways.length > 0 && (
          <Button data-add-gateway="" onClick={() => setDialog({})}><Plus className="mr-1.5 h-4 w-4" />Add a gateway</Button>
        )}
      </div>

      {!canManage && (
        <p className="mb-6 rounded-lg bg-slate-50 p-3 text-sm text-muted-foreground dark:bg-slate-900">
          Only your organisation's admins can add or change gateways. You can choose any of these for the apps you build.
        </p>
      )}

      {gateways.length === 0 ? (
        <EmptyState canManage={canManage} providers={providers.data ?? []} onStart={(p) => setDialog({ provider: p })} />
      ) : (
        <>
          <RoutingPanel gateways={gateways} />
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {gateways.map((g) => (
              <GatewayCard key={g.id} orgId={orgId} gateway={g} canManage={canManage}
                           onEdit={(mode?: Mode) => setDialog({ gateway: g, mode })} onRemove={() => setRemoving(g)} />
            ))}
          </div>
        </>
      )}

      {dialog && providers.data && (
        <GatewayDialog orgId={orgId} providers={providers.data} gateway={dialog.gateway} initialProvider={dialog.provider}
                       initialMode={dialog.mode} onClose={() => setDialog(null)} />
      )}
      {removing && <RemoveDialog orgId={orgId} gateway={removing} onClose={() => setRemoving(null)} />}
    </div>
  );
}

function EmptyState({ canManage, providers, onStart }: { canManage: boolean; providers: { id: string; name: string; tagline: string }[]; onStart: (p: string) => void }) {
  const steps = [
    ["Connect a gateway", "Paste its keys once — Forge checks them with the gateway straight away."],
    ["Build an app", "Forge notices when the app sells something or needs a subscription, and asks which gateway to use."],
    ["Take payments", "Payers go to the gateway's own secure page; the app learns the result from the gateway, never from the browser."],
  ];
  return (
    <div data-payments-empty="" className="rounded-2xl border border-dashed border-slate-300 p-8 dark:border-slate-700">
      <h2 className="text-lg font-semibold">No gateways yet</h2>
      <ol className="mt-4 grid gap-4 md:grid-cols-3">
        {steps.map(([title, text], i) => (
          <li key={title} className="flex gap-3">
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-primary/10 text-sm font-semibold text-primary">{i + 1}</span>
            <span><span className="block text-sm font-medium">{title}</span><span className="block text-sm text-muted-foreground">{text}</span></span>
          </li>
        ))}
      </ol>
      {canManage ? (
        <div className="mt-8">
          <p className="mb-3 text-sm font-medium">Start with the gateway your customers use</p>
          <div className="grid gap-3 md:grid-cols-3">
            {providers.map((p) => (
              <button key={p.id} type="button" data-start-provider={p.id} onClick={() => onStart(p.id)}
                      className="group flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 text-left transition hover:border-primary hover:shadow-sm dark:border-slate-800 dark:bg-slate-900">
                <GatewayMark provider={p.id} />
                <span className="flex-1">
                  <span className="flex items-center gap-1 text-[15px] font-semibold">{p.name}<ArrowRight className="h-4 w-4 opacity-0 transition group-hover:opacity-100" /></span>
                  <span className="mt-0.5 block text-sm text-muted-foreground">{p.tagline}</span>
                </span>
              </button>
            ))}
          </div>
          <p className="mt-4 text-xs text-muted-foreground">Until a gateway is connected, apps that take money use a stand-in checkout that charges nobody, and say so.</p>
        </div>
      ) : (
        <p className="mt-6 text-sm text-muted-foreground">Ask an admin of your organisation to connect one.</p>
      )}
    </div>
  );
}

function RoutingPanel({ gateways }: { gateways: Gateway[] }) {
  const usable = gateways.filter((g) => g.status !== "attention");
  const lines = routingLines(usable);
  if (gateways.length < 2 || lines.length === 0) return null;
  // A gateway no currency is sent to here still serves an app that chooses it
  // without the others — said, so it does not look unused.
  const routed = new Set(lines.map((l) => l.gateway.id));
  const spare = usable.filter((g) => !routed.has(g.id));
  return (
    <section data-routing="" className="mb-6 rounded-xl border border-slate-200 bg-slate-50/60 p-5 dark:border-slate-800 dark:bg-slate-900/50">
      <h2 className="flex items-center gap-2 text-sm font-semibold"><Route className="h-4 w-4" />How payers are routed when an app uses all of them</h2>
      <p className="mt-1 text-xs text-muted-foreground">By the currency a payer pays in: the domestic gateway for its own country's currency, otherwise the international one. Each app can use fewer.</p>
      <ul className="mt-3 flex flex-wrap gap-2">
        {lines.map(({ currency, gateway }) => (
          <li key={currency} data-route={currency} className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-xs ring-1 ring-slate-200 dark:bg-slate-950 dark:ring-slate-800">
            <span className="font-semibold">{currency}</span><ArrowRight className="h-3 w-3 text-muted-foreground" />{gateway.label}
          </li>
        ))}
      </ul>
      {spare.length > 0 && (
        <p className="mt-3 text-xs text-muted-foreground" data-routing-spare="">
          {spare.map((g) => g.label).join(", ")} {spare.length === 1 ? "takes" : "take"} these currencies too, for apps that choose {spare.length === 1 ? "it" : "them"} without the gateway above.
        </p>
      )}
    </section>
  );
}

function ModeLine({ gateway, mode }: { gateway: Gateway; mode: Mode }) {
  const m = gateway.modes[mode];
  const name = mode === "test" ? gateway.testName : "Live";
  const check = m.check;
  let icon = <CircleDashed className="h-4 w-4 text-slate-400" />;
  let text = "Not set";
  if (m.set && check?.ok) {
    icon = <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
    text = `Verified${check.account ? ` — ${check.account}` : ""}${check.checkedAt ? ` · ${timeAgo(check.checkedAt)}` : ""}`;
  } else if (m.set && check && !check.ok) {
    icon = <AlertTriangle className="h-4 w-4 text-amber-600" />;
    text = check.error || "Could not be verified";
  } else if (m.set) {
    text = "Saved, not checked yet";
  }
  return (
    <div data-mode-line={mode} className="flex items-start gap-2 text-sm">
      {icon}
      <span className="min-w-0"><span className="font-medium">{name}</span>
        <span className="ml-1 text-muted-foreground [overflow-wrap:anywhere]">{text}</span></span>
    </div>
  );
}

function GatewayCard({ orgId, gateway, canManage, onEdit, onRemove }: { orgId: string; gateway: Gateway; canManage: boolean; onEdit: (mode?: Mode) => void; onRemove: () => void }) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: gatewaysKey(orgId) });
  const check = useMutation({
    mutationFn: () => gatewayApi.check(orgId, gateway.id),
    onSuccess: (g) => { refresh(); toast[g.status === "attention" ? "error" : "success"](`${g.label}: ${STATUS_WORDS[g.status].toLowerCase()}.`); },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Could not check it"),
  });
  const makeDefault = useMutation({
    mutationFn: () => gatewayApi.edit(orgId, gateway.id, { isDefault: true }),
    onSuccess: () => { refresh(); toast.success(`${gateway.label} is the default gateway for new apps.`); },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Could not change the default"),
  });
  return (
    <div data-gateway={gateway.id} data-gateway-provider={gateway.provider} data-gateway-status={gateway.status}
         className="flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-start gap-3">
        <GatewayMark provider={gateway.provider} />
        <div className="min-w-0 flex-1">
          <h3 className="flex items-center gap-1.5 truncate text-[15px] font-semibold">
            {gateway.label}
            {gateway.isDefault && <span title="Default for new apps" data-default=""><Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" /></span>}
          </h3>
          <p className="text-xs text-muted-foreground">{gateway.providerName}{gateway.isDefault ? " · default" : ""}</p>
        </div>
        {canManage && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button type="button" aria-label={`More for ${gateway.label}`} data-gateway-menu="" className="rounded-md p-1 text-muted-foreground hover:bg-slate-100 hover:text-foreground dark:hover:bg-slate-800">
                {check.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <MoreHorizontal className="h-4 w-4" />}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem data-menu-edit="" onSelect={() => onEdit()}><Pencil className="mr-2 h-4 w-4" />Edit keys and details</DropdownMenuItem>
              <DropdownMenuItem data-menu-check="" onSelect={() => check.mutate()}><RefreshCw className="mr-2 h-4 w-4" />Check the keys again</DropdownMenuItem>
              {!gateway.isDefault && <DropdownMenuItem data-menu-default="" onSelect={() => makeDefault.mutate()}><Star className="mr-2 h-4 w-4" />Make default</DropdownMenuItem>}
              <DropdownMenuSeparator />
              <DropdownMenuItem data-menu-remove="" onSelect={onRemove} className="text-red-600 focus:text-red-600"><Trash2 className="mr-2 h-4 w-4" />Remove</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      <span className={`mt-4 inline-flex w-fit items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_STYLE[gateway.status]}`}>
        {STATUS_WORDS[gateway.status]}
      </span>
      <div className="mt-3 space-y-1.5">
        <ModeLine gateway={gateway} mode="test" />
        <ModeLine gateway={gateway} mode="live" />
      </div>
      <div className="mt-4 border-t pt-3 text-xs text-muted-foreground">
        <p>{coverageWords(gateway)}</p>
        <p className="mt-1 flex flex-wrap gap-1">
          {gateway.currencies.map((c) => <span key={c} className="rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200">{c}</span>)}
        </p>
      </div>
      {canManage && !gateway.modes.live.set && (
        <Button variant="outline" size="sm" className="mt-4" data-add-live="" onClick={() => onEdit("live")}>Add live keys to take real money</Button>
      )}
    </div>
  );
}

function RemoveDialog({ orgId, gateway, onClose }: { orgId: string; gateway: Gateway; onClose: () => void }) {
  const qc = useQueryClient();
  const apps = useQuery({ queryKey: ["gatewayApps", gateway.id], queryFn: () => gatewayApi.apps(orgId, gateway.id) });
  const remove = useMutation({
    mutationFn: () => gatewayApi.remove(orgId, gateway.id),
    onSuccess: (out) => {
      qc.invalidateQueries({ queryKey: gatewaysKey(orgId) });
      toast.success(`${gateway.label} removed.${out?.newDefault ? ` ${out.newDefault.label} is the default gateway for new apps now.` : ""}`);
      onClose();
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Could not remove it"),
  });
  const using = apps.data?.apps ?? [];
  return (
    <Dialog open onOpenChange={(o) => !o && !remove.isPending && onClose()}>
      <DialogContent data-remove-gateway="" className="max-w-md">
        <DialogHeader>
          <DialogTitle>Remove {gateway.label}?</DialogTitle>
          <DialogDescription>Its keys are deleted from Forge. Nothing changes in your {gateway.providerName} account.</DialogDescription>
        </DialogHeader>
        {apps.isLoading ? <p className="text-sm text-muted-foreground">Checking which apps use it…</p> : apps.isError ? (
          <p className="text-sm text-red-700 dark:text-red-300" role="alert" data-apps-unknown="">
            Which apps use it could not be checked just now. An app that takes money through it would stop taking payments.
            <button type="button" className="ml-1 underline" onClick={() => void apps.refetch()}>Check again</button></p>
        ) : using.length > 0 ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200" data-apps-using="">
            <p className="font-medium">{using.length === 1 ? "1 app takes payments" : `${using.length} apps take payments`} through it:</p>
            <ul className="mt-1 list-disc pl-5">{using.slice(0, 8).map((a) => <li key={a.id}>{a.name || "Untitled app"}</li>)}
              {using.length > 8 && <li>and {using.length - 8} more</li>}</ul>
            <p className="mt-2">After removal they take money through their other gateways. An app with no other gateway stops taking payments
              in production — its payers are told payments are not switched on — until you choose a gateway for it again.</p>
          </div>
        ) : <p className="text-sm text-muted-foreground">No app uses it.</p>}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={remove.isPending}>Keep it</Button>
          <Button variant="destructive" data-confirm-remove="" onClick={() => remove.mutate()} disabled={remove.isPending || apps.isLoading || apps.isError}>
            {remove.isPending ? "Removing…" : "Remove"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
