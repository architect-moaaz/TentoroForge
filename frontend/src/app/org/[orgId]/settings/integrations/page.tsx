"use client";

/**
 * /org/[orgId]/settings/integrations — the organisation's credential store.
 *
 * One card per provider, grouped by what it is for, each saying in a glance
 * whether it is connected; the keys live in a dialog opened from the card,
 * so the page is a picture of what is wired up rather than a column of
 * forty inputs. Values are encrypted at rest and pushed into every app at
 * build time, and into an existing app with Sync on its page.
 */

import { use, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  BellRing, Bot, Check, CloudUpload, Cog, CreditCard, ExternalLink, Eye, EyeOff, FileText, Globe, Image as ImageIcon, KeyRound, Mail, PenTool,
  ScanText, Search, Server, Smartphone, Sparkles, Store, Timer, Lock, X as XIcon, type LucideIcon,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  GROUPS, MODEL_LABELS, STATUS_TEXT, type IntegrationEntry, type Status,
  groupByProvider, infoFor, lastUpdated, matches, platformOnly, statusOf,
} from "./catalogue";

const ICONS: Record<string, LucideIcon> = {
  resend: Mail, smtp: Mail, anthropic: Bot, figma: PenTool, uxpilot: PenTool, s3: CloudUpload, paddleocr: ScanText,
  expo_eas: Smartphone, apple_asc: Store, google_play: Store, cron: Timer, encryption: Lock, mcp: Server,
  stripe: CreditCard, embeddings: Sparkles, unsplash: ImageIcon, cloudflare: Globe, route53: Globe, godaddy: Globe, push: BellRing,
};

const STATUS_STYLE: Record<Status, string> = {
  connected: "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-950/40 dark:text-emerald-300",
  partial: "bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-950/40 dark:text-amber-300",
  unset: "bg-slate-100 text-slate-600 ring-slate-500/20 dark:bg-slate-800 dark:text-slate-300",
};

function StatusPill({ status }: { status: Status }) {
  return (
    <span data-status={status} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_STYLE[status]}`}>
      {status === "connected" && <Check className="h-3 w-3" />}
      {STATUS_TEXT[status]}
    </span>
  );
}

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function IntegrationsSettings({ orgId }: { orgId: string }) {
  const { data: entries = [], isLoading } = useQuery({
    queryKey: ["orgIntegrations", orgId],
    queryFn: () => api.get<IntegrationEntry[]>(`/api/orgs/${orgId}/integrations`),
  });
  const [open, setOpen] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const byProvider = useMemo(() => groupByProvider(entries), [entries]);
  const providers = Object.keys(byProvider);
  // The search narrows the cards; the counts stay for the whole page.
  const shown = useMemo(() => providers.filter((p) => matches(p, byProvider[p], query)), [providers, byProvider, query]);
  // A provider managed on another page is neither connected nor missing here.
  const counts = useMemo(() => {
    const c = { connected: 0, partial: 0, unset: 0 };
    for (const p of providers) if (!infoFor(p).managedAt) c[statusOf(byProvider[p])] += 1;
    return c;
  }, [providers, byProvider]);

  if (isLoading) {
    return (
      <div className="p-8">
        <h1 className="mb-2 text-2xl font-semibold">Integrations</h1>
        <p className="text-muted-foreground">Loading…</p>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <KeyRound className="h-6 w-6" /> Integrations
          </h1>
          <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">
            The services your apps are wired to. Every app your organisation builds gets these at build time; an app already built takes
            a change when you press <b>Sync</b> on its page. Design, photo and DNS keys are used by Forge while it builds and never go
            into an app. Values are encrypted at rest and never leave the platform.
          </p>
        </div>
        <div data-summary="" className="flex items-center gap-2 text-sm">
          <StatusPill status="connected" /><span className="text-muted-foreground">{counts.connected}</span>
          <span className="mx-1 text-slate-300">·</span>
          <StatusPill status="partial" /><span className="text-muted-foreground">{counts.partial}</span>
          <span className="mx-1 text-slate-300">·</span>
          <StatusPill status="unset" /><span className="text-muted-foreground">{counts.unset}</span>
        </div>
      </div>

      <div className="relative mb-8 max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input data-integrations-search="" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
               placeholder="Search integrations — a service, a key, what it does…" className="h-10 pl-9" aria-label="Search integrations" />
        {query && (
          <button type="button" aria-label="Clear search" onClick={() => setQuery("")}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
            <XIcon className="h-4 w-4" />
          </button>
        )}
      </div>

      {query && shown.length === 0 && (
        <p data-no-match="" className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-muted-foreground dark:border-slate-700">
          Nothing matches “{query}”. Try the service's name, what it does (email, uploads, mobile) or a key such as AWS_SECRET_ACCESS_KEY.
        </p>
      )}

      <div className="space-y-10">
        {GROUPS.map((group) => {
          const members = shown.filter((p) => infoFor(p).group === group.id);
          if (members.length === 0) return null;
          return (
            <section key={group.id} data-group={group.id}>
              <div className="mb-3">
                <h2 className="text-base font-semibold">{group.title}</h2>
                <p className="text-sm text-muted-foreground">{group.blurb}</p>
              </div>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {members.map((provider) => (
                  <ProviderCard key={provider} orgId={orgId} provider={provider} entries={byProvider[provider]} onOpen={() => setOpen(provider)} />
                ))}
              </div>
            </section>
          );
        })}
      </div>

      {open && (
        <ProviderDialog orgId={orgId} provider={open} entries={byProvider[open] ?? []} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}

function ProviderCard({ orgId, provider, entries, onOpen }: { orgId: string; provider: string; entries: IntegrationEntry[]; onOpen: () => void }) {
  const info = infoFor(provider);
  const Icon = ICONS[provider] ?? Cog;
  const status = statusOf(entries);
  const set = entries.filter((e) => e.is_set).length;
  const updated = when(lastUpdated(entries));
  return (
    <div data-provider={provider} className="flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200">
          <Icon className="h-5 w-5" />
        </span>
        {info.managedAt
          ? <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 ring-1 ring-inset ring-slate-500/20 dark:bg-slate-800 dark:text-slate-300">Managed elsewhere</span>
          : <StatusPill status={status} />}
      </div>
      <h3 className="mt-4 text-[15px] font-semibold text-slate-900 dark:text-white">{info.name}</h3>
      <p className="mt-1 flex-1 text-sm leading-relaxed text-muted-foreground">{info.purpose}</p>
      {info.note && <p className="mt-2 text-xs text-muted-foreground">{info.note}</p>}
      {platformOnly(entries) && <p className="mt-2 text-xs text-muted-foreground">Used by Forge while it builds — never copied into your apps.</p>}
      <div className="mt-4 flex items-center justify-between gap-3">
        <span className="text-xs text-muted-foreground">
          {info.managedAt ? "" : `${set} of ${entries.length} set${updated ? ` · ${updated}` : ""}`}
        </span>
        {info.managedAt ? (
          <Button asChild variant="outline" size="sm">
            <Link href={`/org/${orgId}/settings${info.managedAt.href}`}>{info.managedAt.label}</Link>
          </Button>
        ) : (
          <Button variant={status === "unset" ? "default" : "outline"} size="sm" onClick={onOpen}>
            {status === "unset" ? "Set up" : "Manage"}
          </Button>
        )}
      </div>
    </div>
  );
}

function ProviderDialog({ orgId, provider, entries, onClose }: { orgId: string; provider: string; entries: IntegrationEntry[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const info = infoFor(provider);
  const [values, setValues] = useState<Record<string, string>>({});
  const [shown, setShown] = useState<Record<string, boolean>>({});
  const changes = Object.entries(values).filter(([, v]) => v !== "");
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["orgIntegrations", orgId] });

  const save = useMutation({
    mutationFn: async () => {
      // Only what was typed: a field left blank keeps the value it has.
      for (const [key, value] of changes) await api.put(`/api/orgs/${orgId}/integrations`, { provider, key, value });
      return changes.length;
    },
    onSuccess: (n) => { toast.success(`${info.name}: saved ${n} value${n === 1 ? "" : "s"}.`); setValues({}); invalidate(); onClose(); },
    onError: (err: unknown) => toast.error(`Save failed: ${err instanceof Error ? err.message : "unknown error"}`),
  });
  const clear = useMutation({
    mutationFn: (key: string) => api.put(`/api/orgs/${orgId}/integrations`, { provider, key, value: "" }),
    onSuccess: (_r, key) => { toast.success(`Cleared ${entries.find((e) => e.key === key)?.label ?? key}.`); invalidate(); },
    onError: (err: unknown) => toast.error(`Clear failed: ${err instanceof Error ? err.message : "unknown error"}`),
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-provider-dialog={provider} className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><StatusPill status={statusOf(entries)} />{info.name}</DialogTitle>
          <DialogDescription>{info.purpose}</DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          {entries.map((entry) => {
            const id = `${provider}-${entry.key}`;
            const secret = entry.kind === "password";
            return (
              <div key={entry.key} className="space-y-1.5">
                <div className="flex items-baseline justify-between gap-2">
                  <Label htmlFor={id} className="text-sm">
                    {entry.label}{entry.required && <span className="ml-0.5 text-red-500">*</span>}
                  </Label>
                  <div className="flex items-center gap-3 text-xs">
                    {entry.is_set
                      ? <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-300"><Check className="h-3 w-3" />Set{entry.updated_at ? ` · ${when(entry.updated_at)}` : ""}</span>
                      : <span className="text-muted-foreground">Not set</span>}
                    {entry.help_url && (
                      <a href={entry.help_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-muted-foreground hover:underline">
                        Where to find it <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                </div>
                <div className="flex gap-2">
                  {entry.kind === "select" && entry.options ? (
                    <Select value={values[entry.key] ?? ""} onValueChange={(v) => setValues((p) => ({ ...p, [entry.key]: v }))}>
                      <SelectTrigger id={id} className="w-full">
                        <SelectValue placeholder={entry.is_set ? "Keep the current choice" : entry.default ?? "Choose…"} />
                      </SelectTrigger>
                      <SelectContent>
                        {entry.options.map((opt) => <SelectItem key={opt} value={opt}>{MODEL_LABELS[opt] ?? opt}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  ) : (
                    <div className="relative flex-1">
                      <Input id={id} type={secret && !shown[entry.key] ? "password" : "text"} autoComplete="new-password"
                             placeholder={entry.is_set ? "•••••••• — leave blank to keep" : entry.default ?? (entry.kind === "url" ? "https://…" : "")}
                             value={values[entry.key] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [entry.key]: e.target.value }))}
                             className={secret ? "pr-9" : ""} />
                      {secret && (
                        <button type="button" aria-label={shown[entry.key] ? "Hide" : "Show"} onClick={() => setShown((s) => ({ ...s, [entry.key]: !s[entry.key] }))}
                                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                          {shown[entry.key] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      )}
                    </div>
                  )}
                  {entry.is_set && (
                    <Button type="button" variant="outline" size="icon" title="Clear this value" onClick={() => clear.mutate(entry.key)} disabled={clear.isPending}>
                      <XIcon className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            Saved values are encrypted and shown only as set. An app already built takes a change when you press Sync on its page.
          </p>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="button" onClick={() => save.mutate()} disabled={save.isPending || changes.length === 0}>
            {save.isPending ? "Saving…" : changes.length ? `Save ${changes.length} value${changes.length === 1 ? "" : "s"}` : "Nothing to save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function IntegrationsSettingsPage({ params }: { params: Promise<{ orgId: string }> }) {
  const { orgId } = use(params);
  return <IntegrationsSettings orgId={orgId} />;
}
