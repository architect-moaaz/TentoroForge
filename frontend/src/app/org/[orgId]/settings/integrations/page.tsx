"use client";

/**
 * /org/[orgId]/settings/integrations — org-scoped credential store for the
 * Forge platform. Fetches the provider catalog + this org's is_set state,
 * renders one Card per provider with a form per key, PUTs on save.
 *
 * Values entered here are pushed into each generated app's .env.local at
 * generation time and via the Sync button on the project page.
 *
 * Spec: docs/superpowers/specs/2026-07-22-integrations-settings.md.
 */

import { use, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { KeyRound, ExternalLink, Check, X as XIcon } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface CatalogEntry {
  provider: string;
  key: string;
  label: string;
  kind: "password" | "text" | "url" | "select";
  required: boolean;
  default: string | null;
  help_url: string | null;
  options: string[] | null;
}

/** Friendly labels for known model ids. Anything not here shows the id as-is. */
const MODEL_LABELS: Record<string, string> = {
  "claude-opus-4-8": "Claude Opus 4.8 — most capable",
  "claude-opus-4-7": "Claude Opus 4.7",
  "claude-sonnet-5": "Claude Sonnet 5 — balanced (latest)",
  "claude-sonnet-4-6": "Claude Sonnet 4.6 — balanced",
  "claude-haiku-4-5-20251001": "Claude Haiku 4.5 — fastest",
  "claude-fable-5": "Claude Fable 5",
};

interface IntegrationEntry extends CatalogEntry {
  is_set: boolean;
  updated_at: string | null;
}

const PROVIDER_LABELS: Record<string, string> = {
  resend: "Email (Resend)",
  smtp: "Email (SMTP) — overrides Resend when host is set",
  anthropic: "AI (Anthropic)",
  s3: "File storage (Amazon S3)",
  cron: "Scheduled jobs",
  twilio: "SMS (Twilio)",
  stripe: "Payments (Stripe)",
};

function groupByProvider<T extends { provider: string }>(rows: T[]): Record<string, T[]> {
  const out: Record<string, T[]> = {};
  for (const r of rows) (out[r.provider] ??= []).push(r);
  return out;
}

function IntegrationsSettings({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();

  const { data: entries = [], isLoading } = useQuery({
    queryKey: ["orgIntegrations", orgId],
    queryFn: () => api.get<IntegrationEntry[]>(`/api/orgs/${orgId}/integrations`),
  });

  const grouped = useMemo(() => groupByProvider(entries), [entries]);
  const providers = Object.keys(grouped).sort();

  if (isLoading) {
    return (
      <div className="p-8">
        <h1 className="text-2xl font-semibold mb-2">Integrations</h1>
        <p className="text-muted-foreground">Loading…</p>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold mb-2 flex items-center gap-2">
          <KeyRound className="w-6 h-6" /> Integrations
        </h1>
        <p className="text-muted-foreground">
          Credentials configured here get baked into every app your org
          generates. Rotate a key and click <b>Sync</b> on the project page to
          push the update into an existing app. Values are encrypted at rest
          and never leave the platform.
        </p>
      </div>

      <div className="space-y-6">
        {providers.map((provider) => (
          <ProviderCard
            key={provider}
            provider={provider}
            entries={grouped[provider]}
            orgId={orgId}
            invalidateKey={["orgIntegrations", orgId]}
          />
        ))}
      </div>
    </div>
  );
}

function ProviderCard({
  provider,
  entries,
  orgId,
  invalidateKey,
}: {
  provider: string;
  entries: IntegrationEntry[];
  orgId: string;
  invalidateKey: readonly unknown[];
}) {
  const queryClient = useQueryClient();
  const [values, setValues] = useState<Record<string, string>>({});

  const mutation = useMutation({
    mutationFn: async () => {
      // Send only fields the user typed into (skips fields left blank so
      // we don't clobber an existing value with an empty submit).
      const changes = Object.entries(values).filter(([, v]) => v !== "");
      if (changes.length === 0) {
        return { skipped: true, count: 0 } as const;
      }
      for (const [key, value] of changes) {
        await api.put(`/api/orgs/${orgId}/integrations`, {
          provider,
          key,
          value,
        });
      }
      return { skipped: false, count: changes.length } as const;
    },
    onSuccess: (r) => {
      if (r.skipped) {
        toast.info("No changes to save.");
      } else {
        toast.success(`Saved ${r.count} value${r.count === 1 ? "" : "s"}.`);
        setValues({});
        queryClient.invalidateQueries({ queryKey: invalidateKey });
      }
    },
    onError: (err: any) => {
      toast.error(`Save failed: ${err?.message ?? "unknown error"}`);
    },
  });

  const clearMutation = useMutation({
    mutationFn: (key: string) =>
      api.put(`/api/orgs/${orgId}/integrations`, { provider, key, value: "" }),
    onSuccess: (_r, key) => {
      toast.success(`Cleared ${key}.`);
      queryClient.invalidateQueries({ queryKey: invalidateKey });
    },
    onError: (err: any) =>
      toast.error(`Clear failed: ${err?.message ?? "unknown error"}`),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">
          {PROVIDER_LABELS[provider] ?? provider}
        </CardTitle>
        <CardDescription>
          {entries.length} field{entries.length === 1 ? "" : "s"} · Not stored
          on your generated apps until you sync
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {entries.map((entry) => (
            <div key={entry.key} className="grid gap-2">
              <div className="flex items-baseline justify-between gap-2">
                <Label htmlFor={`${provider}-${entry.key}`} className="text-sm">
                  {entry.label}
                  {entry.required && (
                    <span className="text-red-500 ml-0.5">*</span>
                  )}
                </Label>
                <div className="flex items-center gap-2">
                  {entry.is_set ? (
                    <Badge variant="secondary" className="text-xs gap-1">
                      <Check className="w-3 h-3" /> Set
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-xs">
                      Not set
                    </Badge>
                  )}
                  {entry.help_url && (
                    <a
                      href={entry.help_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-muted-foreground hover:underline flex items-center gap-1"
                    >
                      Help <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </div>
              </div>
              <div className="flex gap-2">
                {entry.kind === "select" && entry.options ? (
                  <Select
                    value={values[entry.key] ?? ""}
                    onValueChange={(v) =>
                      setValues((prev) => ({ ...prev, [entry.key]: v }))
                    }
                  >
                    <SelectTrigger
                      id={`${provider}-${entry.key}`}
                      className="w-full"
                    >
                      <SelectValue
                        placeholder={
                          entry.is_set
                            ? "•••••••• (leave blank to keep current)"
                            : entry.default ?? "Select…"
                        }
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {entry.options.map((opt) => (
                        <SelectItem key={opt} value={opt}>
                          {MODEL_LABELS[opt] ?? opt}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    id={`${provider}-${entry.key}`}
                    type={entry.kind === "password" ? "password" : "text"}
                    autoComplete="new-password"
                    placeholder={
                      entry.is_set
                        ? "•••••••• (leave blank to keep current)"
                        : entry.default ?? ""
                    }
                    value={values[entry.key] ?? ""}
                    onChange={(e) =>
                      setValues((v) => ({ ...v, [entry.key]: e.target.value }))
                    }
                  />
                )}
                {entry.is_set && (
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    title="Clear this value"
                    onClick={() => clearMutation.mutate(entry.key)}
                    disabled={clearMutation.isPending}
                  >
                    <XIcon className="w-4 h-4" />
                  </Button>
                )}
              </div>
              {entry.updated_at && (
                <p className="text-xs text-muted-foreground">
                  Last updated {new Date(entry.updated_at).toLocaleString()}
                </p>
              )}
            </div>
          ))}
          <div className="pt-2">
            <Button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
            >
              {mutation.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function IntegrationsSettingsPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <IntegrationsSettings orgId={orgId} />;
}
