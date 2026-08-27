"use client";

/**
 * Deployment history for a project — status, URL, who deployed, how
 * long it took, and which commit + app version was shipped, plus a
 * rollback affordance on prior succeeded ones.
 * Backed by GET /api/projects/{id}/deployments (20 rows, newest first).
 */

import { useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Undo2,
  ExternalLink,
  User as UserIcon,
  Clock,
  GitCommit,
  Tag,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { toast } from "sonner";

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const now = Date.now();
  const s = Math.floor((now - then) / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function formatDuration(sec: number | null): string {
  if (sec == null) return "—";
  if (sec < 60) return `${Math.round(sec)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return s ? `${m}m ${s}s` : `${m}m`;
}

interface Deployment {
  id: string;
  target: string;
  status: string;
  url: string | null;
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  triggered_by_name: string | null;
  triggered_by_email: string | null;
  git_sha: string | null;
  git_sha_short: string | null;
  git_commit_subject: string | null;
  app_version: string | null;
  vercel_deployment_id: string | null;
}

interface Props {
  projectId: string;
}

export function DeploymentHistory({ projectId }: Props) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["deployments", projectId],
    queryFn: () => api.get<Deployment[]>(`/api/projects/${projectId}/deployments`),
    refetchInterval: 5_000,
  });

  const rollback = useMutation({
    mutationFn: (deploymentId: string) =>
      api.post<{ url: string; rollback_id: string }>(
        `/api/deployments/${deploymentId}/rollback`,
        {},
      ),
    onSuccess: (r) => {
      toast.success(`Rolled back — live at ${r.url}`);
      qc.invalidateQueries({ queryKey: ["deployments", projectId] });
    },
    onError: (err) => toast.error(`Rollback failed: ${(err as Error).message}`),
  });

  // The latest successful deploy is the one currently live; earlier
  // ones can be rolled back to. Failed rows never get a rollback button.
  const latestSucceededId = useMemo(
    () => data?.find((r) => r.status === "succeeded")?.id ?? null,
    [data],
  );

  if (isLoading) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        <Loader2 className="mr-1.5 inline h-3 w-3 animate-spin" />
        Loading history…
      </div>
    );
  }

  const rows = data ?? [];
  if (rows.length === 0) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        No deployments yet — click Publish to ship your first one.
      </div>
    );
  }

  return (
    <div className="divide-y">
      {rows.map((r) => {
        const canRollback =
          r.status === "succeeded" &&
          r.id !== latestSucceededId &&
          !!r.vercel_deployment_id;
        const isLive = r.id === latestSucceededId;
        return (
          <div key={r.id} className="flex items-start gap-3 px-3 py-3">
            <div className="pt-0.5">
              {r.status === "succeeded" ? (
                <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" />
              ) : r.status === "failed" ? (
                <XCircle className="h-4 w-4 shrink-0 text-red-500" />
              ) : (
                <Loader2 className="h-4 w-4 shrink-0 animate-spin text-blue-500" />
              )}
            </div>

            <div className="min-w-0 flex-1 space-y-1">
              {/* Row 1: URL or error, plus a subtle "current" tag on the live one. */}
              <div className="flex items-center gap-2">
                {r.url ? (
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noreferrer"
                    className="truncate font-mono text-xs hover:underline"
                    title={r.url}
                  >
                    {r.url.replace(/^https?:\/\//, "")}
                  </a>
                ) : (
                  <span className="truncate text-xs text-muted-foreground">
                    {r.error ?? r.status}
                  </span>
                )}
                {isLive && (
                  <span className="rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-800">
                    current
                  </span>
                )}
              </div>

              {/* Row 2: meta — when, who, how long, commit + version. */}
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                <span title={r.created_at ?? undefined}>
                  {relativeTime(r.created_at)}
                </span>
                <span className="flex items-center gap-1">
                  <UserIcon className="h-3 w-3" />
                  {r.triggered_by_name ??
                    r.triggered_by_email ??
                    "unknown"}
                </span>
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {formatDuration(r.duration_seconds)}
                </span>
                {r.git_sha_short && (
                  <span
                    className="flex items-center gap-1 font-mono"
                    title={
                      r.git_commit_subject
                        ? `${r.git_sha}\n${r.git_commit_subject}`
                        : r.git_sha ?? undefined
                    }
                  >
                    <GitCommit className="h-3 w-3" />
                    {r.git_sha_short}
                  </span>
                )}
                {r.app_version && (
                  <span
                    className="flex items-center gap-1"
                    title="package.json version"
                  >
                    <Tag className="h-3 w-3" />v{r.app_version}
                  </span>
                )}
                <span className="text-muted-foreground/70">
                  {r.target}
                </span>
              </div>

              {/* Row 3: error text (if failed). */}
              {r.status === "failed" && r.error && (
                <div className="truncate text-[11px] text-red-600" title={r.error}>
                  {r.error}
                </div>
              )}
            </div>

            <div className="flex shrink-0 items-center gap-1">
              {r.url && (
                <Button variant="ghost" size="icon" className="h-6 w-6" asChild>
                  <a href={r.url} target="_blank" rel="noreferrer" title="Open">
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </Button>
              )}
              {canRollback && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-6 gap-1 text-[10px]"
                  disabled={rollback.isPending}
                  onClick={() => rollback.mutate(r.id)}
                  title="Re-promote this deployment"
                >
                  <Undo2 className="h-3 w-3" />
                  Rollback
                </Button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
