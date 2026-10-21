"use client";

/**
 * Assistants: whether Claude, or any MCP client, may connect to this app and
 * use it as one of its people. Off by default. The tools are the app's own
 * processes and records, written from its definition; each runs as the person
 * whose token it is, under the same rules as the screens.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot } from "lucide-react";

import { api } from "@/lib/api";

type Roles = string[] | null;
export type AppMcp = {
  enabled: boolean;
  changedAt?: number | null;
  path: string;
  connectPage: string;
  tools: {
    workflows: { tool: string; name: string; roles: Roles }[];
    records: { find: string; get: string; name: string; roles: Roles }[];
  };
};

export const appMcpKey = (projectId: string) => ["app-mcp", projectId];

function who(roles: Roles): string {
  if (!roles || !roles.length) return "anyone signed in";
  return roles.map((r) => (r === "*" ? "everyone" : r === "@signed-in" ? "anyone signed in" : r)).join(", ");
}

export function AssistantsSection({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: appMcpKey(projectId),
    queryFn: () => api.get<AppMcp>(`/api/projects/${projectId}/app-mcp`),
  });
  const set = useMutation({
    mutationFn: (enabled: boolean) => api.put<AppMcp>(`/api/projects/${projectId}/app-mcp`, { enabled }),
    onSuccess: (next) => qc.setQueryData(appMcpKey(projectId), next),
  });

  if (isLoading) return <p className="text-sm text-slate-500">Reading whether assistants may connect…</p>;
  if (error || !data) return <p className="text-sm text-red-700 dark:text-red-300">Could not read the assistant setting.</p>;

  const flows = data.tools.workflows;
  const records = data.tools.records;
  return (
    <div className="space-y-4">
      <label className="flex items-start justify-between gap-4 rounded-md border p-3">
        <span className="space-y-0.5">
          <span className="flex items-center gap-2 text-sm font-medium"><Bot className="h-4 w-4" /> Let AI assistants use this app</span>
          <span className="block text-xs text-slate-500">
            {data.enabled
              ? "On. People connect from the app's “Connect an AI assistant” page, each with their own token."
              : "Off. The app's MCP address answers “not found” and the connect page is hidden."}
          </span>
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={data.enabled}
          aria-label="Let AI assistants use this app"
          disabled={set.isPending}
          onClick={() => set.mutate(!data.enabled)}
          className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-60 ${
            data.enabled ? "bg-emerald-600" : "bg-slate-300 dark:bg-slate-700"
          }`}
        >
          <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
            data.enabled ? "translate-x-5" : "translate-x-0.5"
          }`} />
        </button>
      </label>
      {set.isError && <p className="text-sm text-red-700 dark:text-red-300">The setting could not be changed. Try again.</p>}
      <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600 dark:text-slate-300">
        <li>An assistant acts as the person whose token it uses: it can run what their role can run and see what their role can see, under every rule the app has.</li>
        <li>The preview follows this switch at once. The live app follows it with its <b>next publish</b>.</li>
        <li>The address is the app&rsquo;s <code>{data.path}</code>; people make and revoke tokens at <code>{data.connectPage}</code>.</li>
      </ul>
      <div className="space-y-2">
        <h4 className="text-sm font-medium">What an assistant can do ({flows.length + records.length * 2} tools)</h4>
        {!flows.length && !records.length && (
          <p className="text-sm text-slate-500">The tool list is written with the app&rsquo;s next build or Smith turn.</p>
        )}
        <ul className="divide-y rounded-md border text-sm" data-app-mcp-tools="">
          {flows.map((w) => (
            <li key={w.tool} className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2">
              <span><code className="text-xs">{w.tool}</code> <span className="text-slate-500">runs {w.name}</span></span>
              <span className="text-xs text-slate-500">{who(w.roles)}</span>
            </li>
          ))}
          {records.map((r) => (
            <li key={r.find} className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2">
              <span><code className="text-xs">{r.find}</code> / <code className="text-xs">{r.get}</code> <span className="text-slate-500">reads {r.name}</span></span>
              <span className="text-xs text-slate-500">{who(r.roles)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
