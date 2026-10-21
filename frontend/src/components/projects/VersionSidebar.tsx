"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitCommit, Clock, History, Loader2, RotateCcw, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { Version } from "@/types/project";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/** One recorded change to the application (`revert.history`). */
type BlueprintVersion = {
  version: number; at: string | null; request: string; interpretation: string;
  undo: boolean; current: boolean; restorable: boolean;
};
type BlueprintHistory = { current: number; versions: BlueprintVersion[] };

const when = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

/**
 * Build history for an application with a Blueprint: every recorded change,
 * newest first, each with what was asked, and Restore on the earlier ones.
 * A Blueprint application's repository has no commits, so the git list below
 * showed nothing but publish records and no way back (Mark 8, 2026-10-17).
 */
function BlueprintVersions({ projectId, history }: { projectId: string; history: BlueprintHistory }) {
  const qc = useQueryClient();
  const [asked, setAsked] = useState<BlueprintVersion | null>(null);
  const restore = useMutation({
    mutationFn: (version: number) => api.post<{ restored: number; version: number }>(
      `/api/projects/${projectId}/blueprint/restore`, { version }),
    onSuccess: (out) => {
      toast.success(`Restored version ${out.restored}. Publish to put it live.`);
      setAsked(null);
      void qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "The version was not restored."),
  });
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-baseline justify-between border-b px-3 py-2">
        <h3 className="text-sm font-medium">Version History</h3>
        <span className="text-[11px] text-muted-foreground">now at v{history.current} · {history.versions.length} changes</span>
      </div>
      <div className="flex-1 overflow-y-auto" data-blueprint-versions="">
        {history.versions.map((v) => (
          <div key={v.version} className="flex items-start gap-2 border-b px-3 py-2.5 last:border-b-0 hover:bg-muted/50">
            <span className="mt-0.5 shrink-0 rounded bg-muted px-1.5 py-px font-mono text-[10px] text-muted-foreground">v{v.version}</span>
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-1 text-xs font-medium" title={v.interpretation}>
                {v.undo && <Undo2 className="h-3 w-3 shrink-0 text-muted-foreground" />}
                <span className="truncate">{v.request || v.interpretation || "A change"}</span>
              </p>
              {v.at && (
                <div className="mt-0.5 flex items-center gap-0.5 text-[10px] text-muted-foreground">
                  <Clock className="h-2.5 w-2.5" />{when(v.at)}
                </div>
              )}
            </div>
            {v.current ? (
              <span className="shrink-0 rounded-full bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-700">Current</span>
            ) : v.restorable ? (
              <Button variant="outline" size="sm" className="h-7 shrink-0 text-[11px]" onClick={() => setAsked(v)}>
                <RotateCcw className="mr-1 h-3 w-3" />Restore
              </Button>
            ) : null}
          </div>
        ))}
      </div>
      <Dialog open={!!asked} onOpenChange={(open) => !open && setAsked(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Restore version {asked?.version}?</DialogTitle>
            <DialogDescription>
              The app goes back to how it stood right after “{asked?.request || "that change"}”, and every screen, rule and
              table is written out again to match. The restore is recorded as a change of its own, so it can be undone.
              The live app changes only when you publish.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAsked(null)} disabled={restore.isPending}>Cancel</Button>
            <Button onClick={() => asked && restore.mutate(asked.version)} disabled={restore.isPending}>
              {restore.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <History className="mr-1.5 h-3.5 w-3.5" />}
              Restore version {asked?.version}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

interface VersionSidebarProps {
  projectId: string;
}

export function VersionSidebar({ projectId }: VersionSidebarProps) {
  // The Blueprint's own history first; a project with none keeps the git list.
  const blueprint = useQuery({
    queryKey: ["project", projectId, "blueprint-history"],
    queryFn: () => api.get<BlueprintHistory>(`/api/projects/${projectId}/blueprint/history`),
    retry: false,
    refetchInterval: 15000,
  });
  const { data: versions, isLoading } = useQuery({
    queryKey: ["project", projectId, "versions"],
    queryFn: () => api.get<Version[]>(`/api/projects/${projectId}/versions`),
    refetchInterval: 10000,
  });

  if (blueprint.data?.versions.length) return <BlueprintVersions projectId={projectId} history={blueprint.data} />;
  if (blueprint.isLoading || isLoading) {
    return (
      <div className="flex items-center justify-center p-4 text-sm text-muted-foreground">
        Loading versions...
      </div>
    );
  }

  if (!versions?.length) {
    return (
      <div className="flex items-center justify-center p-4 text-sm text-muted-foreground">
        No versions yet
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-3 py-2">
        <h3 className="text-sm font-medium">Version History</h3>
      </div>
      <div className="flex-1 overflow-y-auto">
        {versions.map((version, index) => (
          <div
            key={version.id}
            className="border-b px-3 py-2.5 last:border-b-0 hover:bg-muted/50"
          >
            <div className="flex items-start gap-2">
              <GitCommit className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">
                  {version.message}
                </p>
                <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                  {version.commit_hash && (
                    <span className="font-mono">
                      {version.commit_hash.slice(0, 7)}
                    </span>
                  )}
                  <span className="flex items-center gap-0.5">
                    <Clock className="h-2.5 w-2.5" />
                    {new Date(version.created_at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </div>
              </div>
              {index === 0 && (
                <span className="rounded-full bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-700">
                  Latest
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
