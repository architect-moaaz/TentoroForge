"use client";

/**
 * Test and Production: the two sides of a published app.
 *
 * The switch decides where Publish sends the app. On Test, the app goes to its
 * own address with its own demo data, and the live app is untouched; on
 * Production, the live app is updated. Shown in the Publish dialog and in
 * App settings → Publishing; both read and change the same switch
 * (`/api/projects/{id}/publish-target`).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FlaskConical, Globe } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";

export type Side = "test" | "production";

export interface SideState {
  id: string;
  status: string;
  url: string | null;
  deployment_url: string | null;
  app_version: string | null;
  promoted_from: string | null;
  finished_at: string | null;
}

export interface PublishStatus {
  target: Side;
  test: SideState | null;
  production: SideState | null;
  test_address: string;
  /** Where people open the live app: its main address (own domain, else
   *  `<app>.apps.tentoro.ai`) once that answers, else its Vercel address. */
  production_address?: string | null;
  /** The app has changed since it was last tried on Test. */
  untested_changes: boolean;
  /** Test runs a newer version than production. */
  test_ahead: boolean;
}

export const publishStatusKey = (projectId?: string) => ["project", projectId, "publish-status"];

export function usePublishStatus(projectId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: publishStatusKey(projectId),
    queryFn: () => api.get<PublishStatus>(`/api/projects/${projectId}/publish-status`),
    enabled: !!projectId && enabled,
  });
}

export function useSetPublishTarget(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (target: Side) => api.put<{ target: Side }>(`/api/projects/${projectId}/publish-target`, { target }),
    onSuccess: ({ target }) => {
      qc.setQueryData<PublishStatus | undefined>(publishStatusKey(projectId), (old) => (old ? { ...old, target } : old));
      toast.success(target === "test" ? "Publish now goes to the test version" : "Publish now updates the live app");
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "The switch did not change"),
  });
}

/** The Test | Production switch. */
export function PublishTargetSwitch({
  projectId,
  value,
  disabled = false,
}: {
  projectId: string | undefined;
  value: Side;
  disabled?: boolean;
}) {
  const set = useSetPublishTarget(projectId);
  const options: { side: Side; label: string; hint: string }[] = [
    { side: "test", label: "Test", hint: "Its own address and demo data — the live app is not touched" },
    { side: "production", label: "Production", hint: "Updates the live app" },
  ];
  return (
    <div role="radiogroup" aria-label="Publish to" className="grid grid-cols-2 gap-1 rounded-md border bg-muted/40 p-1">
      {options.map((o) => {
        const on = value === o.side;
        return (
          <button
            key={o.side}
            type="button"
            role="radio"
            aria-checked={on}
            title={o.hint}
            disabled={disabled || set.isPending}
            onClick={() => !on && set.mutate(o.side)}
            className={`flex items-center justify-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-60 ${
              on
                ? o.side === "test"
                  ? "bg-amber-500 text-white shadow-sm"
                  : "bg-emerald-600 text-white shadow-sm"
                : "text-muted-foreground hover:bg-background"
            }`}
          >
            {o.side === "test" ? <FlaskConical className="h-3.5 w-3.5" /> : <Globe className="h-3.5 w-3.5" />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function SideLine({ label, state, address, fallback }: {
  label: string; state: SideState | null; address?: string | null; fallback: string;
}) {
  const url = state ? address || state.url : null;
  return (
    <div className="flex min-w-0 items-center gap-2 text-xs">
      <span className="w-20 shrink-0 font-medium">{label}</span>
      {url ? (
        <a href={url} target="_blank" rel="noreferrer"
           className="flex min-w-0 items-center gap-1 font-mono text-muted-foreground hover:text-foreground">
          <ExternalLink className="h-3 w-3 shrink-0" />
          <span className="truncate">{url.replace(/^https?:\/\//, "")}</span>
        </a>
      ) : (
        <span className="text-muted-foreground">{fallback}</span>
      )}
      {state?.finished_at && (
        <span className="ml-auto shrink-0 text-muted-foreground">{new Date(state.finished_at).toLocaleString()}</span>
      )}
    </div>
  );
}

/** One side's address as a small link with its tag, for the toolbar. */
export function SideLink({ side, url }: { side: Side; url: string }) {
  const test = side === "test";
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="flex min-w-0 max-w-[280px] items-center gap-1 text-[11px] font-mono text-muted-foreground hover:text-foreground"
      title={test ? `Test version at ${url}` : `Live app at ${url}`}
    >
      <ExternalLink className="h-3 w-3 shrink-0" />
      <span className={`rounded px-1 font-sans text-[10px] font-semibold ${
        test
          ? "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200"
          : "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200"
      }`}>{test ? "Test" : "Live"}</span>
      <span className="truncate">{url.replace(/^https?:\/\//, "")}</span>
    </a>
  );
}

/** What each side runs now, and what that means for the next publish. */
export function SidesSummary({ status }: { status: PublishStatus }) {
  return (
    <div className="space-y-1.5 rounded border bg-muted/20 px-3 py-2">
      <SideLine label="Test" state={status.test} fallback={`Not published yet — it will be at ${status.test_address.replace(/^https?:\/\//, "")}`} />
      <SideLine label="Production" state={status.production} address={status.production_address} fallback="Not live yet" />
      {status.test_ahead && (
        <p className="text-xs text-muted-foreground">The test version is newer than the live app.</p>
      )}
    </div>
  );
}
