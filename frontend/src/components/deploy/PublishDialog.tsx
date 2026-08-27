"use client";

/**
 * Publish flow modal — target picker + live SSE progress stream.
 *
 * DB is source of truth; SSE is best-effort. On open we hit /latest so
 * a returning user sees the last successful URL instead of a stuck
 * spinner. When SSE closes without a terminal frame (network drop,
 * server reload, cancelled task) we poll /latest until we see a
 * terminal state so the modal never lies about the deploy.
 */

import { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  Circle,
  Loader2,
  XCircle,
  ExternalLink,
  Copy,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { useDeployStream, DeployEvent } from "@/hooks/useDeployStream";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { MobileBuildsPanel } from "./MobileBuildsPanel";

interface LatestDeployment {
  id: string;
  target: string;
  status: string;
  url: string | null;
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
}

interface Props {
  projectId: string | undefined;
  /** Threaded through so the Mobile tab can deep-link to
   *  /org/[orgId]/settings/integrations when credentials are missing. */
  orgId?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Which tab the dialog opens on. Callers that surface mobile
   *  separately (a distinct toolbar entry) pass "mobile"; the default
   *  "web" preserves the existing Publish button behavior. */
  initialTab?: "web" | "mobile";
}

const STAGES: Array<{
  key: DeployEvent["stage"];
  label: string;
}> = [
  { key: "snapshot", label: "Packaging app source" },
  { key: "provision_db", label: "Provisioning database" },
  { key: "upload", label: "Uploading to Vercel" },
  { key: "build", label: "Building" },
  { key: "activate", label: "Activating deployment" },
];

export function PublishDialog({
  projectId,
  orgId,
  open,
  onOpenChange,
  initialTab = "web",
}: Props) {
  const [target, setTarget] = useState<"vercel" | "tentoro-cloud">("vercel");
  const [started, setStarted] = useState(false);
  const [reconciledUrl, setReconciledUrl] = useState<string | null>(null);
  const [reconciledError, setReconciledError] = useState<string | null>(null);
  const [priorFinishedAt, setPriorFinishedAt] = useState<string | null>(null);
  const { events, status, start, reset } = useDeployStream(projectId);
  const reconcilePoll = useRef<number | null>(null);

  const publish = () => {
    if (started) return;
    setStarted(true);
    void start();
  };

  // On open, reconcile against the DB. Do NOT auto-start a deploy —
  // deploys only run when the user explicitly clicks "Publish now" or
  // "Republish". Opening the modal (e.g. to switch to the Mobile tab
  // or just check the last URL) must never trigger a redeploy.
  useEffect(() => {
    if (!open || !projectId) return;
    let cancelled = false;
    (async () => {
      try {
        const latest = await api.get<LatestDeployment | null>(
          `/api/projects/${projectId}/deployments/latest`,
        );
        if (cancelled || !latest) return;
        // In-flight deploys started elsewhere → attach the stream so
        // the user sees live progress rather than a stale idle state.
        const inFlight =
          latest.status !== "succeeded" &&
          latest.status !== "succeeded_with_warnings" &&
          latest.status !== "failed";
        if (inFlight) {
          publish();
          return;
        }
        if (
          (latest.status === "succeeded" ||
            latest.status === "succeeded_with_warnings") &&
          latest.url
        ) {
          setReconciledUrl(latest.url);
          setPriorFinishedAt(latest.finished_at);
          if (latest.status === "succeeded_with_warnings" && latest.error) {
            setReconciledError(latest.error);
          }
        } else if (latest.status === "failed") {
          setReconciledError(latest.error ?? "Last publish failed");
          setPriorFinishedAt(latest.finished_at);
        }
      } catch {
        /* /latest is best-effort — leave the idle state as-is */
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, projectId]);

  // When SSE ends without a terminal frame, reconcile against /latest.
  // Poll every 3s until succeeded/failed or 10 min. Only runs after the
  // user has actually kicked off a deploy this session (started=true) —
  // otherwise opening the modal to peek at Mobile would silently poll
  // for a deploy that never started.
  useEffect(() => {
    if (!open || !projectId || !started) return;
    if (status !== "error" && status !== "idle") return;
    // status==='error' can also mean the stream broke mid-flight — DB
    // may still be BUILDING. So poll instead of trusting error status.
    const terminal = events.some(
      (e) =>
        e.stage === "done" || e.stage === "error" || e.stage === "smoke_failed",
    );
    if (terminal) return;

    let alive = true;
    let elapsed = 0;
    const tick = async () => {
      if (!alive) return;
      try {
        const latest = await api.get<LatestDeployment | null>(
          `/api/projects/${projectId}/deployments/latest`,
        );
        if (!alive || !latest) return;
        if (
          (latest.status === "succeeded" ||
            latest.status === "succeeded_with_warnings") &&
          latest.url
        ) {
          setReconciledUrl(latest.url);
          if (latest.status === "succeeded_with_warnings" && latest.error) {
            setReconciledError(latest.error);
          }
          return;
        }
        if (latest.status === "failed") {
          setReconciledError(latest.error ?? "Publish failed");
          return;
        }
      } catch {
        /* ignore transient errors */
      }
      elapsed += 3000;
      if (elapsed < 10 * 60 * 1000) {
        reconcilePoll.current = window.setTimeout(tick, 3000);
      }
    };
    reconcilePoll.current = window.setTimeout(tick, 3000);
    return () => {
      alive = false;
      if (reconcilePoll.current) window.clearTimeout(reconcilePoll.current);
    };
  }, [open, projectId, status, events]);

  // Reset everything when the modal closes so the next open starts clean.
  useEffect(() => {
    if (open) return;
    setStarted(false);
    setReconciledUrl(null);
    setReconciledError(null);
    setPriorFinishedAt(null);
    reset();
    if (reconcilePoll.current) window.clearTimeout(reconcilePoll.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const doneEvent = events.find((e) => e.stage === "done");
  const errorEvent = events.find((e) => e.stage === "error");
  const url =
    reconciledUrl ??
    (doneEvent?.data as { url?: string } | undefined)?.url ??
    "";
  const errorMessage = reconciledError ?? errorEvent?.message ?? null;

  const isDone = !!url;
  const isError = !isDone && !!errorMessage;

  const currentStage = () => {
    if (isDone || isError) return null;
    const seen = new Set(events.map((e) => e.stage));
    for (const s of STAGES) if (!seen.has(s.key)) return s.key;
    return STAGES[STAGES.length - 1].key;
  };
  const cur = currentStage();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Publish</DialogTitle>
        </DialogHeader>

        <Tabs defaultValue={initialTab} className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="web">Web</TabsTrigger>
            <TabsTrigger value="mobile" disabled={!projectId}>
              Mobile app
            </TabsTrigger>
          </TabsList>

          <TabsContent value="web" className="mt-3 space-y-2">
        {/* Target picker — Tentoro Cloud reserved for later. */}
        <div className="space-y-1 py-1">
          <label className="text-xs font-medium text-muted-foreground">
            Deploy target
          </label>
          <Select
            value={target}
            onValueChange={(v) => setTarget(v as "vercel" | "tentoro-cloud")}
            disabled={started}
          >
            <SelectTrigger className="h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="vercel">Vercel</SelectItem>
              <SelectItem value="tentoro-cloud" disabled>
                Tentoro Cloud (coming soon)
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/*
          Idle state — no deploy in flight this session. If there's a
          prior success we already show its URL below; either way we
          gate the actual deploy behind an explicit click so opening
          the modal never has a side-effect.
        */}
        {!started && (
          <div className="flex items-center justify-between rounded border bg-muted/30 px-3 py-2 text-xs">
            <span className="text-muted-foreground">
              {reconciledUrl
                ? priorFinishedAt
                  ? `Last published ${new Date(priorFinishedAt).toLocaleString()}`
                  : "Previously published"
                : "This project hasn't been published yet."}
            </span>
            <Button size="sm" onClick={publish}>
              {reconciledUrl ? "Republish" : "Publish now"}
            </Button>
          </div>
        )}

        {started && <div className="space-y-2 py-2">

          {STAGES.map((s) => {
            const idx = STAGES.findIndex((x) => x.key === s.key);
            const curIdx = cur ? STAGES.findIndex((x) => x.key === cur) : -1;
            const stagePassed = isDone || (curIdx >= 0 && idx < curIdx);
            const stageCurrent = !isDone && !isError && s.key === cur;
            const stageErrored = isError && s.key === cur;
            return (
              <div key={s.key} className="flex items-center gap-2 text-sm">
                {stageErrored ? (
                  <XCircle className="h-4 w-4 text-red-500" />
                ) : stageCurrent ? (
                  <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                ) : stagePassed ? (
                  <CheckCircle2 className="h-4 w-4 text-green-500" />
                ) : (
                  <Circle className="h-4 w-4 text-muted-foreground" />
                )}
                <span
                  className={
                    stageCurrent
                      ? "font-medium"
                      : stagePassed
                        ? "text-muted-foreground line-through"
                        : "text-muted-foreground"
                  }
                >
                  {s.label}
                </span>
              </div>
            );
          })}
        </div>}

        {started && isDone && url && (
          <div className="rounded border border-green-200 bg-green-50 p-3 space-y-2">
            <div className="text-sm font-medium text-green-900">
              Live at
            </div>
            <div className="flex items-center gap-1 text-xs font-mono">
              <span className="flex-1 truncate">{url}</span>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => {
                  navigator.clipboard.writeText(url);
                  toast.success("Copied");
                }}
              >
                <Copy className="h-3 w-3" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                asChild
              >
                <a href={url} target="_blank" rel="noreferrer">
                  <ExternalLink className="h-3 w-3" />
                </a>
              </Button>
            </div>
          </div>
        )}

        {isError && (
          <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-900">
            {errorMessage}
          </div>
        )}
          </TabsContent>

          <TabsContent value="mobile" className="mt-3">
            {projectId && orgId ? (
              <MobileBuildsPanel projectId={projectId} orgId={orgId} />
            ) : (
              <div className="rounded border bg-muted/40 px-3 py-4 text-xs text-muted-foreground text-center">
                Open a project to build a mobile app.
              </div>
            )}
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
