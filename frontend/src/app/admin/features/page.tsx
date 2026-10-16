"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Lock } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError } from "@/lib/api";
import { adminApi, adminKeys } from "@/lib/admin-api";
import { FEATURE_GROUP_NAMES, type AdminFeature } from "@/lib/admin-types";
import { FeatureSwitch, switchValue } from "@/components/admin/FeatureSwitch";
import { when } from "@/components/admin/PeopleTable";

export default function AdminFeaturesPage() {
  const qc = useQueryClient();
  const features = useQuery({ queryKey: adminKeys.features, queryFn: adminApi.features });
  const set = useMutation({
    mutationFn: ({ key, enabled, reason }: { key: string; enabled: boolean | null; reason: string }) => adminApi.setPlatformFeature(key, enabled, reason),
    onSuccess: () => { toast.success("Platform default saved"); qc.invalidateQueries({ queryKey: ["admin", "features"] }); qc.invalidateQueries({ queryKey: ["admin", "org"] }); qc.invalidateQueries({ queryKey: ["admin", "audit"] }); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Not saved"),
  });
  const rows = features.data?.features ?? [];
  const groups = (features.data?.groups ?? []) as AdminFeature["group"][];
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Features</h1>
        <p className="text-sm text-muted-foreground">
          What every organisation gets unless it has a setting of its own. Everything is on except what takes an app&apos;s source code out of the platform
          (<Lock className="inline h-3 w-3 text-amber-500" />). Switch a single organisation from its page; the platform default here applies to every organisation without one.
        </p>
      </div>
      {groups.map((g) => (
        <section key={g}>
          <h2 className="mb-2 text-base font-semibold">{FEATURE_GROUP_NAMES[g]}</h2>
          <div className="rounded-lg border bg-white dark:bg-slate-900">
            <Table>
              <TableHeader>
                <TableRow><TableHead>Feature</TableHead><TableHead>Catalogue</TableHead><TableHead>Platform default</TableHead><TableHead>Organisations with their own setting</TableHead><TableHead>Enforced</TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {rows.filter((f) => f.group === g).map((f) => (
                  <TableRow key={f.key} data-testid={`feature-${f.key}`}>
                    <TableCell>
                      <div className="flex items-center gap-1.5 font-medium">{f.name}{f.source_out && <Lock className="h-3 w-3 text-amber-500" aria-label="takes source out" />}</div>
                      <div className="text-xs text-muted-foreground">{f.description}</div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{f.default_on ? "on" : "off"}</TableCell>
                    <TableCell>
                      <FeatureSwitch value={switchValue(f.platform)} inheritLabel={`Catalogue (${f.default_on ? "on" : "off"})`} featureName={f.name}
                                     pending={set.isPending} onChange={(enabled, reason) => set.mutate({ key: f.key, enabled, reason })} />
                      {f.platform && <div className="mt-1 text-[11px] text-muted-foreground">{f.platform.reason} · {f.platform.by_email || "—"} · {when(f.platform.at)}</div>}
                    </TableCell>
                    <TableCell className="text-sm">{f.org_overrides || <span className="text-muted-foreground">none</span>}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{f.enforced === "api" ? "screens and API" : "screens"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </section>
      ))}
    </div>
  );
}
