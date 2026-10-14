"use client";

/**
 * The app's own addresses — one component, two places: App settings →
 * Domains, and the Custom domain card of the Publish dialog. Both read and
 * change the same record (`/api/projects/{id}/domains`), so a change in one
 * shows in the other, and Smith ("put it on app.acme.com") changes it too.
 *
 * Forge attaches the address to the app's Vercel project, shows the records
 * to add (read from Vercel), and watches until it answers; the owner adds
 * the records where their DNS is managed, then waits or presses Check now.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, ExternalLink, Loader2, Pencil, RefreshCw, Star, Trash2, Wand2 } from "lucide-react";
import { toast } from "sonner";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export interface DomainRecord {
  host: string;
  type: string;
  value: string;
  why: string;
}

export interface DomainView {
  name: string;
  kind: "subdomain" | "apex" | "tentoro";
  main: boolean;
  status: "waiting" | "live" | "failed";
  detail: string;
  records: DomainRecord[];
  checkedAt?: string | null;
  /** The `www.` companion of a bare domain: it sends people there. */
  redirectTo?: string;
  addedAt?: string;
  liveAt?: string;
  works?: boolean | null;
  worksDetail?: string;
  /** Who runs the domain's DNS, from its nameservers ("Cloudflare"), or "". */
  dnsHost?: string;
  /** Forge wrote this address's records at a connected DNS account. */
  written?: boolean;
}

export interface WriteResult {
  written: boolean;
  conflicts: boolean;
  replaceable?: boolean;
  provider: string;
  message: string;
}

export interface DomainsState {
  domains: DomainView[];
  oldAddress: "redirect" | "keep";
  vercelAddress: string;
  mainAddress: string;
  elsewhere: { what: string; address: string }[];
  appsDomain: string;
  /** The organisation's connected DNS accounts, by name. */
  dnsAccounts: string[];
}

const KIND_LABEL: Record<DomainView["kind"], string> = {
  subdomain: "Your subdomain",
  apex: "Your domain",
  tentoro: "Tentoro address",
};

function ago(iso?: string | null): string {
  if (!iso) return "";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s} seconds ago`;
  if (s < 3600) return `${Math.round(s / 60)} minutes ago`;
  if (s < 86400) return `${Math.round(s / 3600)} hours ago`;
  return `${Math.round(s / 86400)} days ago`;
}

function StatusPill({ d }: { d: DomainView }) {
  const base = "rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap";
  if (d.status === "live" && d.works === false)
    return <span className={`${base} bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200`}>Live · sign-in not moved yet</span>;
  if (d.status === "live")
    return <span className={`${base} bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200`}>Live</span>;
  if (d.status === "failed")
    return <span className={`${base} bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200`}>Not working</span>;
  return <span className={`${base} bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200`}>Waiting for DNS</span>;
}

function copy(text: string) {
  navigator.clipboard.writeText(text).then(
    () => toast.success("Copied"),
    () => toast.error("Could not copy; select the text instead"),
  );
}

export function DomainsPanel({ projectId, compact = false }: { projectId: string; compact?: boolean }) {
  const qc = useQueryClient();
  const key = ["project", projectId, "domains"];
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [written, setWritten] = useState<Record<string, WriteResult>>({});
  const params = useParams<{ orgId?: string }>();

  const { data, isLoading, error } = useQuery({
    queryKey: key,
    queryFn: () => api.get<DomainsState>(`/api/projects/${projectId}/domains`),
    // While an address waits, the watch is checking it; read what it found.
    refetchInterval: (q) =>
      (q.state.data as DomainsState | undefined)?.domains.some((d) => d.status === "waiting" || d.works === false)
        ? 30_000
        : false,
  });

  const done = (next: DomainsState) => qc.setQueryData(key, next);
  const fail = (e: unknown) => toast.error(e instanceof Error ? e.message : "That did not work");

  const add = useMutation({
    mutationFn: (n: string) => api.post<DomainsState>(`/api/projects/${projectId}/domains`, { name: n }),
    onSuccess: (next) => {
      done(next);
      setName("");
      toast.success("Address added. Add the record below where your DNS is managed.");
    },
    onError: fail,
  });
  const check = useMutation({
    mutationFn: (n: string) => api.post<DomainsState>(`/api/projects/${projectId}/domains/${encodeURIComponent(n)}/check`),
    onSuccess: done,
    onError: fail,
  });
  const makeMain = useMutation({
    mutationFn: (n: string) => api.post<DomainsState>(`/api/projects/${projectId}/domains/${encodeURIComponent(n)}/main`),
    onSuccess: (next) => {
      done(next);
      toast.success("Main address changed. Sign-in and links follow it once it is live.");
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (n: string) => api.delete<DomainsState>(`/api/projects/${projectId}/domains/${encodeURIComponent(n)}`),
    onSuccess: (next) => {
      done(next);
      toast.success("Address removed");
    },
    onError: fail,
  });
  const writeRecords = useMutation({
    mutationFn: ({ n, replace }: { n: string; replace: boolean }) =>
      api.post<DomainsState & { result: WriteResult }>(
        `/api/projects/${projectId}/domains/${encodeURIComponent(n)}/records`,
        { replace },
      ),
    onSuccess: (next, { n }) => {
      const { result, ...view } = next;
      done(view);
      setWritten((w) => ({ ...w, [n]: result }));
      if (result.written) toast.success(`Records added at ${result.provider}`);
    },
    onError: fail,
  });
  const rename = useMutation({
    mutationFn: (label: string) =>
      api.put<DomainsState>(`/api/projects/${projectId}/domains/tentoro`, { name: label }),
    onSuccess: (next) => {
      done(next);
      setRenaming(null);
      toast.success("Address renamed");
    },
    onError: fail,
  });
  const oldAddress = useMutation({
    mutationFn: (mode: "redirect" | "keep") =>
      api.put<DomainsState>(`/api/projects/${projectId}/domains/old-address`, { mode }),
    onSuccess: done,
    onError: fail,
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" /> Reading the app&rsquo;s addresses…
      </div>
    );
  }
  if (error || !data) {
    return <p className="text-sm text-red-700 dark:text-red-300">{error instanceof Error ? error.message : "Could not read the app's addresses."}</p>;
  }

  const busy = (m: { isPending: boolean; variables?: unknown }, n: string) => m.isPending && m.variables === n;

  return (
    <div className="space-y-4">
      {!compact && (
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Your app answers at <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">{data.vercelAddress.replace("https://", "")}</code>.
          Add your own domain or a subdomain of it; Forge shows the record to add and tells you in chat when it is live.
        </p>
      )}

      {data.domains.length === 0 && compact && (
        <p className="text-xs text-slate-500">Put the app on your own address, such as app.your-company.com.</p>
      )}

      <ul className="space-y-3">
        {data.domains.map((d) => (
          <li key={d.name} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
            <div className="flex flex-wrap items-center gap-2">
              <span className="break-all font-mono text-sm font-medium">{d.name}</span>
              <StatusPill d={d} />
              {d.main && (
                <span className="rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-medium text-sky-800 dark:bg-sky-900/40 dark:text-sky-200">
                  {d.status === "live" ? "Main address" : "Will be main"}
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-slate-500">
              {d.redirectTo ? `Sends people to ${d.redirectTo}` : KIND_LABEL[d.kind]}
              {d.checkedAt ? ` · checked ${ago(d.checkedAt)}` : ""}
              {d.status === "live" && d.liveAt ? ` · live since ${new Date(d.liveAt).toLocaleString()}` : ""}
            </p>
            {d.status !== "live" && d.detail && <p className="mt-2 text-xs text-slate-700 dark:text-slate-300">{d.detail}</p>}
            {d.status === "live" && d.works === false && d.worksDetail && (
              <p className="mt-2 text-xs text-amber-800 dark:text-amber-300">{d.worksDetail}</p>
            )}

            {d.status !== "live" && d.records.length > 0 && (
              <div className="mt-2 space-y-1.5">
                <p className="text-xs font-medium text-slate-700 dark:text-slate-200">
                  Add {d.records.length === 1 ? "this record" : "these records"} where{" "}
                  {d.name.split(".").slice(-2).join(".")}&rsquo;s DNS is managed:
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-slate-500">
                        <th className="py-1 pr-3 font-medium">Name</th>
                        <th className="py-1 pr-3 font-medium">Type</th>
                        <th className="py-1 pr-3 font-medium">Value</th>
                        <th className="py-1" />
                      </tr>
                    </thead>
                    <tbody>
                      {d.records.map((r) => (
                        <tr key={`${r.type}-${r.host}-${r.value}`} className="border-t border-slate-100 dark:border-slate-800" title={r.why}>
                          <td className="py-1 pr-3 font-mono break-all">{r.host}</td>
                          <td className="py-1 pr-3 font-mono">{r.type}</td>
                          <td className="py-1 pr-3 font-mono break-all">{r.value}</td>
                          <td className="py-1 text-right">
                            <Button variant="ghost" size="icon" className="h-6 w-6" aria-label={`Copy ${r.type} value`} onClick={() => copy(r.value)}>
                              <Copy className="h-3 w-3" />
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-[11px] text-slate-500">It usually works within minutes and can take up to two days.</p>
                {(data.dnsAccounts ?? []).length > 0 ? (
                  <div className="space-y-1.5 pt-1">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => writeRecords.mutate({ n: d.name, replace: false })}
                      disabled={writeRecords.isPending && writeRecords.variables?.n === d.name}
                    >
                      {writeRecords.isPending && writeRecords.variables?.n === d.name ? (
                        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                      ) : (
                        <Wand2 className="mr-1 h-3 w-3" />
                      )}
                      Add the records for me
                    </Button>
                    {written[d.name] && !written[d.name].written && (
                      <div
                        role="status"
                        className={`rounded-md p-2 text-xs ${
                          written[d.name].conflicts
                            ? "bg-amber-50 text-amber-900 dark:bg-amber-900/30 dark:text-amber-100"
                            : "bg-slate-50 text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                        }`}
                      >
                        <p>{written[d.name].message}</p>
                        {written[d.name].conflicts && written[d.name].replaceable && (
                          <Button
                            size="sm"
                            variant="outline"
                            className="mt-2"
                            onClick={() => writeRecords.mutate({ n: d.name, replace: true })}
                          >
                            Replace {written[d.name].provider ? `at ${written[d.name].provider}` : "them"}
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                ) : (
                  d.dnsHost &&
                  ["Cloudflare", "Route 53", "GoDaddy"].includes(d.dnsHost) && (
                    <p className="text-[11px] text-slate-600 dark:text-slate-300">
                      {d.name.split(".").slice(-2).join(".")}&rsquo;s DNS is at {d.dnsHost}.{" "}
                      {params?.orgId ? (
                        <Link href={`/org/${params.orgId}/settings/integrations`} className="underline">
                          Connect {d.dnsHost}
                        </Link>
                      ) : (
                        <>Connect {d.dnsHost} under Settings → Integrations</>
                      )}{" "}
                      and Forge adds the records for you.
                    </p>
                  )
                )}
              </div>
            )}

            <div className="mt-3 flex flex-wrap gap-2">
              {d.status !== "live" || d.works === false ? (
                <Button size="sm" onClick={() => check.mutate(d.name)} disabled={busy(check, d.name)}>
                  {busy(check, d.name) ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <RefreshCw className="mr-1 h-3 w-3" />}
                  Check now
                </Button>
              ) : (
                <Button size="sm" variant="outline" asChild>
                  <a href={`https://${d.name}`} target="_blank" rel="noreferrer">
                    <ExternalLink className="mr-1 h-3 w-3" /> Open
                  </a>
                </Button>
              )}
              {!d.main && !d.redirectTo && (
                <Button size="sm" variant="outline" onClick={() => makeMain.mutate(d.name)} disabled={busy(makeMain, d.name)}>
                  <Star className="mr-1 h-3 w-3" /> Make main address
                </Button>
              )}
              {d.kind !== "tentoro" ? (
                <Button size="sm" variant="ghost" onClick={() => remove.mutate(d.name)} disabled={busy(remove, d.name)}>
                  <Trash2 className="mr-1 h-3 w-3" /> Remove
                </Button>
              ) : renaming === null && (
                <Button size="sm" variant="ghost" onClick={() => setRenaming(d.name.split(".")[0])}>
                  <Pencil className="mr-1 h-3 w-3" /> Rename
                </Button>
              )}
            </div>
            {d.kind === "tentoro" && renaming !== null && (
              <form
                className="mt-2 flex flex-wrap items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (renaming.trim()) rename.mutate(renaming.trim());
                }}
              >
                <label htmlFor={`domain-rename-${projectId}`} className="sr-only">New name</label>
                <div className="flex min-w-0 flex-1 items-center gap-1">
                  <Input
                    id={`domain-rename-${projectId}`}
                    value={renaming}
                    onChange={(e) => setRenaming(e.target.value)}
                    className="min-w-0 flex-1 font-mono text-sm"
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <span className="shrink-0 font-mono text-xs text-slate-500">.{d.name.split(".").slice(1).join(".")}</span>
                </div>
                <Button type="submit" size="sm" disabled={!renaming.trim() || rename.isPending}>
                  {rename.isPending ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                  Rename
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setRenaming(null)}>
                  Cancel
                </Button>
              </form>
            )}
          </li>
        ))}
      </ul>

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) add.mutate(name.trim());
        }}
      >
        <label htmlFor={`domain-add-${projectId}`} className="sr-only">Your domain or subdomain</label>
        <Input
          id={`domain-add-${projectId}`}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="your-domain.com or app.your-domain.com"
          className="min-w-0 flex-1 font-mono text-sm"
          autoComplete="off"
          spellCheck={false}
        />
        <Button type="submit" size="sm" disabled={!name.trim() || add.isPending}>
          {add.isPending ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
          Add domain
        </Button>
      </form>

      {!compact && data.domains.some((d) => d.kind !== "tentoro" || d.main) && (
        <div className="space-y-2 border-t border-slate-200 pt-3 text-sm dark:border-slate-700">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label htmlFor={`domain-old-${projectId}`}>
              When someone opens <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">{data.vercelAddress.replace("https://", "")}</code>
            </label>
            <select
              id={`domain-old-${projectId}`}
              value={data.oldAddress}
              onChange={(e) => oldAddress.mutate(e.target.value as "redirect" | "keep")}
              className="rounded-md border border-slate-200 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900"
            >
              <option value="redirect">Send them to the main address</option>
              <option value="keep">Keep answering there too</option>
            </select>
          </div>
          <p className="flex items-center gap-1.5 text-xs text-slate-500">
            <Check className="h-3 w-3" /> Sign-in, email links and the phone app use the main address:{" "}
            <span className="font-mono">{data.mainAddress.replace("https://", "")}</span>
          </p>
          {data.elsewhere.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-slate-700 dark:text-slate-200">
                Register these where they are set when the main address changes:
              </p>
              {data.elsewhere.map((x) => (
                <div key={x.address} className="flex items-center gap-2 text-xs">
                  <span className="text-slate-500">{x.what}</span>
                  <span className="min-w-0 flex-1 break-all font-mono">{x.address}</span>
                  <Button variant="ghost" size="icon" className="h-6 w-6" aria-label={`Copy ${x.what}`} onClick={() => copy(x.address)}>
                    <Copy className="h-3 w-3" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
