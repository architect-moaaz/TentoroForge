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
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { useDeployStream, DeployEvent } from "@/hooks/useDeployStream";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { MobileBuildsPanel } from "./MobileBuildsPanel";
import { LockedPanel } from "@/components/features/Locked";
import { DomainsPanel } from "./DomainsPanel";
import { useAppSettingsStore } from "@/stores/appSettings";
import { PublishTargetSwitch, SidesSummary, usePublishStatus, type Side } from "./PublishSides";

interface LatestDeployment {
  id: string;
  target: string;
  status: string;
  /** The app's own address: its main domain, else the production alias — the same after every publish. */
  url: string | null;
  deployment_url?: string | null;
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
  /** The organisation lacks "Mobile builds": the tab shows the lock, not the panel. */
  mobileLocked?: boolean;
}

/** What the build found when it used the app (GET /api/projects/{id}/check). */
interface CheckNote {
  checked: boolean;
  /** The app changed since anyone last used it (an edit outside Smith). */
  stale?: boolean;
  pages: number;
  working: number;
  failing: Array<{ route: string; detail: string; stale?: boolean }>;
  processes: string[];
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
  mobileLocked = false,
}: Props) {
  // WHERE PUBLISH GOES: the app's Test | Production switch.
  const { data: sides, refetch: refetchSides } = usePublishStatus(projectId, open);
  const side: Side = sides?.target ?? "production";
  const [confirmProduction, setConfirmProduction] = useState(false);
  const [resetTestData, setResetTestData] = useState(false);
  const [publishedSide, setPublishedSide] = useState<Side | null>(null);
  const [started, setStarted] = useState(false);
  const [reconciledUrl, setReconciledUrl] = useState<string | null>(null);
  const [reconciledError, setReconciledError] = useState<string | null>(null);
  const [priorFinishedAt, setPriorFinishedAt] = useState<string | null>(null);
  const { events, status, start, reset } = useDeployStream(projectId);
  const [check, setCheck] = useState<CheckNote | null>(null);
  const reconcilePoll = useRef<number | null>(null);
  const openSettings = useAppSettingsStore((s) => s.open);

  const publish = (body?: { environment?: Side; promote?: boolean; reset_test_data?: boolean }) => {
    if (started) return;
    setStarted(true);
    setConfirmProduction(false);
    setPublishedSide(body?.promote ? "production" : body?.environment ?? side);
    void start(body);
  };

  /** Publish pressed: to Test at once; to Production, once more when the
   *  changes were not tried on Test first. */
  const publishToSide = () => {
    if (side === "production" && sides?.untested_changes && !confirmProduction) {
      setConfirmProduction(true);
      return;
    }
    publish(side === "test" ? { environment: "test", reset_test_data: resetTestData } : { environment: "production" });
  };

  // On open, reconcile against the DB. Do NOT auto-start a deploy —
  // deploys only run when the user explicitly clicks "Publish now" or
  // "Republish". Opening the modal (e.g. to switch to the Mobile tab
  // or just check the last URL) must never trigger a redeploy.
  // WHAT DOES NOT WORK YET IS SAID BEFORE IT GOES LIVE. The build used every
  // page and process; what still fails is named here, above the button —
  // a warning, never a gate.
  useEffect(() => {
    if (!open || !projectId) return;
    let cancelled = false;
    api.get<CheckNote>(`/api/projects/${projectId}/check`)
      .then((note) => { if (!cancelled) setCheck(note); })
      .catch(() => { if (!cancelled) setCheck(null); });
    return () => { cancelled = true; };
  }, [open, projectId]);

  useEffect(() => {
    if (!open || !projectId) return;
    let cancelled = false;
    (async () => {
      try {
        setReconciledUrl(null);
        setReconciledError(null);
        setPriorFinishedAt(null);
        const latest = await api.get<LatestDeployment | null>(
          `/api/projects/${projectId}/deployments/latest?environment=${side}`,
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
  }, [open, projectId, side]);

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
          `/api/projects/${projectId}/deployments/latest${publishedSide ? `?environment=${publishedSide}` : ""}`,
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
    setConfirmProduction(false);
    setResetTestData(false);
    setPublishedSide(null);
    reset();
    if (reconcilePoll.current) window.clearTimeout(reconcilePoll.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const doneEvent = events.find((e) => e.stage === "done");
  // A finished publish changes what each side runs.
  useEffect(() => {
    if (doneEvent) void refetchSides();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!doneEvent]);
  const errorEvent = events.find((e) => e.stage === "error");
  const builtUrl =
    reconciledUrl ??
    (doneEvent?.data as { url?: string } | undefined)?.url ??
    "";
  // The live app is shown at its main address (own domain, else
  // apps.tentoro.ai) once that answers, not at the Vercel one it was built at.
  const url = builtUrl && publishedSide !== "test" && sides?.production_address ? sides.production_address : builtUrl;
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
        {/* WHERE PUBLISH GOES: Test (its own address and demo data) or
            Production (the live app). Promote sends what Test runs. */}
        {sides && (
          <div className="space-y-2 py-1">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-muted-foreground">Publish to</span>
            </div>
            <PublishTargetSwitch projectId={projectId} value={side} disabled={started} />
            <SidesSummary status={sides} />
          </div>
        )}

        {/*
          Idle state — no deploy in flight this session. If there's a
          prior success we already show its URL below; either way we
          gate the actual deploy behind an explicit click so opening
          the modal never has a side-effect.
        */}
        {!started && check?.checked && (check.failing.length > 0 || check.processes.length > 0) && (
          <div
            role="status"
            className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200"
          >
            <p className="font-medium">
              Not everything works yet — {check.working} of {check.pages} pages
              {check.processes.length > 0 ? `, and ${check.processes.length} process${check.processes.length === 1 ? "" : "es"},` : ""}
              {" "}passed the build&rsquo;s check.
            </p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {check.failing.slice(0, 5).map((f) => (
                <li key={f.route}>
                  <code>{f.route}</code> — {f.detail}
                  {f.stale && <span className="text-amber-700/80 dark:text-amber-300/80"> (found before the page was last changed)</span>}
                </li>
              ))}
              {check.processes.slice(0, 5).map((name) => (
                <li key={name}>{name} does not run through</li>
              ))}
            </ul>
            <p className="mt-1">Publishing puts them live as they are. Tell Smith &ldquo;check the app again and fix everything that still fails&rdquo; first.</p>
          </div>
        )}

        {!started && check?.checked && check.stale && (
          <p role="status" className="text-xs text-amber-800 dark:text-amber-300">
            The app has changed since it was last checked. Ask Smith to check it again before
            publishing if you want to be sure it all still works.
          </p>
        )}

        {!started && confirmProduction && (
          <div role="alert" className="space-y-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
            <p className="font-medium">
              {sides?.test ? "The app has changed since it was last tried on Test." : "This version has not been tried on Test."}
            </p>
            <p>Publishing now puts these changes on the live app straight away.</p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="destructive" onClick={() => publish({ environment: "production" })}>
                Publish to Production anyway
              </Button>
              <Button size="sm" variant="outline" onClick={() => { setConfirmProduction(false); publish({ environment: "test" }); }}>
                Publish to Test first
              </Button>
            </div>
          </div>
        )}

        {!started && !confirmProduction && (
          <div className="space-y-2 rounded border bg-muted/30 px-3 py-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted-foreground">
                {side === "test"
                  ? reconciledUrl
                    ? `Test version last published ${priorFinishedAt ? new Date(priorFinishedAt).toLocaleString() : ""}`
                    : "Not published to Test yet. The live app is not affected."
                  : reconciledUrl
                    ? priorFinishedAt
                      ? `Live app last published ${new Date(priorFinishedAt).toLocaleString()}`
                      : "Previously published"
                    : "This project hasn't been published yet."}
              </span>
              <Button size="sm" onClick={publishToSide}>
                {side === "test" ? "Publish to Test" : "Publish to Production"}
              </Button>
            </div>
            {side === "test" && sides?.test && (
              <label className="flex items-center gap-2 text-muted-foreground">
                <input type="checkbox" checked={resetTestData} onChange={(e) => setResetTestData(e.target.checked)} />
                Start the test data again from demo data
              </label>
            )}
            {sides?.test && (sides.test_ahead || !sides.production) && (
              <div className="flex items-center justify-between gap-2 border-t pt-2">
                <span className="text-muted-foreground">Send exactly what Test runs to the live app.</span>
                <Button size="sm" variant="outline" onClick={() => publish({ promote: true })}>
                  Promote to Production
                </Button>
              </div>
            )}
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
              {publishedSide === "test" ? "Test version live at" : "Live at"}
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

        {/* The app's own address — the same panel as App settings → Domains. */}
        {projectId && (
          <div className="space-y-2 border-t pt-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-medium">Custom domain</div>
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0 text-xs"
                onClick={() => {
                  openSettings("domains");
                  onOpenChange(false);
                }}
              >
                Manage in App settings
              </Button>
            </div>
            <DomainsPanel projectId={projectId} compact />
          </div>
        )}
          </TabsContent>

          <TabsContent value="mobile" className="mt-3">
            {mobileLocked ? (
              <LockedPanel name="Mobile builds" />
            ) : projectId && orgId ? (
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
