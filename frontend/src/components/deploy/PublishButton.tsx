"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, FlaskConical, Globe, Lock, Smartphone, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api";
import { PublishDialog } from "./PublishDialog";
import { lockedNote } from "@/lib/features";
import { explainLock } from "@/components/features/Locked";
import {
  SideLink,
  publishStatusKey,
  usePublishStatus,
  useSetPublishTarget,
  type PublishStatus,
  type Side,
} from "./PublishSides";

interface LatestDeployment {
  id: string;
  status: string;
  url: string | null;
  finished_at: string | null;
}

// Slim shape — we only need `status` here. Kept local so this component
// doesn't drag the full Project type into its bundle just for one field.
interface ProjectStatusInfo {
  status: "draft" | "generating" | "ready" | "error" | "archived";
}

interface Props {
  projectId: string | undefined;
  /** Threaded into PublishDialog so the Mobile tab can link to the
   *  org's Settings → Integrations page when credentials are missing. */
  orgId?: string;
  size?: "sm" | "default";
  /** The organisation lacks "Publish to the web": the button stays, locked. */
  lockedWeb?: boolean;
  /** The organisation lacks "Mobile builds". */
  lockedMobile?: boolean;
}

export function PublishButton({ projectId, orgId, size = "sm", lockedWeb = false, lockedMobile = false }: Props) {
  const [open, setOpen] = useState(false);
  // Which tab the dialog will open on. The main "Publish" button leaves
  // it on "web" (unchanged behavior). The secondary Smartphone icon
  // button opens directly on "mobile" so users don't have to click
  // through Publish — a click that used to trigger an accidental
  // web redeploy on its way to the Mobile tab.
  const [initialTab, setInitialTab] = useState<"web" | "mobile">("web");

  // Bug B-020.6: without this, clicking Publish on a project that hadn't
  // finished (or hadn't even started) generation kicked off a deploy that
  // immediately errored — an empty output_dir has nothing to snapshot.
  // Poll status so as soon as the first build completes the button lights
  // up on its own without a page refresh.
  const { data: statusData } = useQuery({
    queryKey: ["project-status", projectId],
    queryFn: () =>
      api.get<ProjectStatusInfo>(`/api/projects/${projectId}`),
    enabled: !!projectId,
    // UNTIL IT IS READY, ASK OFTEN. The application is handed over the moment
    // it boots, and Publish must light within seconds of that — not half a
    // minute later, while the person reads "built" and sees a disabled button.
    refetchInterval: (q) =>
      q.state.data?.status === "ready" ? 30_000 : 5_000,
  });
  const projectStatus = statusData?.status;
  const isReady = projectStatus === "ready";

  // Poll the latest deploy so a returning user sees the live URL right
  // in the toolbar, and the "Publish" affordance turns into "Republish"
  // once there's a live app.
  const { data } = useQuery({
    queryKey: ["deployment-latest", projectId],
    queryFn: () =>
      api.get<LatestDeployment | null>(
        `/api/projects/${projectId}/deployments/latest`,
      ),
    enabled: !!projectId,
    refetchInterval: (q) => {
      // While a publish is in flight, poll often; once terminal, back off.
      const s = q.state.data?.status;
      if (s && !["succeeded", "failed"].includes(s)) return 3_000;
      return 30_000;
    },
  });

  // WHERE PUBLISH GOES, and BOTH ADDRESSES: the live app's (its main
  // address — own domain, else apps.tentoro.ai — once that answers) and the
  // test version's, each one click away whichever way the switch is set.
  const { data: sides } = usePublishStatus(projectId, isReady && !lockedWeb);
  const productionUrl = sides
    ? sides.production ? sides.production_address || sides.production.url : null
    : data?.status === "succeeded" ? data.url : null;
  const testUrl = sides?.test?.url ?? null;

  // Picking Test or Production from the dropdown sets where Publish goes, then
  // opens the dialog on that side. The cache is updated at once so the dialog
  // opens on the chosen side without waiting for the PUT to come back; the
  // mutation then persists the switch (the same one App settings → Publishing
  // and the dialog show).
  const qc = useQueryClient();
  const setTarget = useSetPublishTarget(projectId);
  const choosePublish = (target: Side) => {
    if (lockedWeb) { explainLock("Publish to the web"); return; }
    qc.setQueryData<PublishStatus | undefined>(
      publishStatusKey(projectId),
      (old) => (old ? { ...old, target } : old),
    );
    if (sides?.target !== target) setTarget.mutate(target);
    setInitialTab("web");
    setOpen(true);
  };

  return (
    <div className="flex min-w-0 items-center gap-1.5">
      {(productionUrl || testUrl) && (
        <div className="flex min-w-0 flex-col items-end gap-0.5 leading-tight">
          {productionUrl && <SideLink side="production" url={productionUrl} />}
          {testUrl && <SideLink side="test" url={testUrl} />}
        </div>
      )}
      {(() => {
        const disabled = !projectId || (!isReady && !lockedWeb);
        const title =
          lockedWeb ? lockedNote("Publish to the web") :
          !projectId
            ? undefined
            : projectStatus === "generating"
              ? "App is still being built — Publish will be available once generation finishes."
              : projectStatus === "error"
                ? "Last build errored. Fix the error before publishing."
                : projectStatus === "draft"
                  ? "Nothing to publish yet — build the app first."
                  : projectStatus === "archived"
                    ? "This project is archived."
                    : undefined;
        const label = (
          <>
            {lockedWeb ? <Lock className="mr-1.5 h-3.5 w-3.5" /> : <Upload className="mr-1.5 h-3.5 w-3.5" />}
            {productionUrl ? "Republish" : "Publish"}
            {!lockedWeb && <ChevronDown className="ml-1 h-3.5 w-3.5 opacity-70" />}
          </>
        );
        // Locked: no menu — the click explains why it is locked, as before.
        if (lockedWeb) {
          return (
            <Button
              variant="default" size={size} className="shrink-0" data-locked="publish"
              title={title} onClick={() => explainLock("Publish to the web")}
            >
              {label}
            </Button>
          );
        }
        // Click Publish → choose Test or Production → the dialog opens on it.
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="default" size={size} className="shrink-0" disabled={disabled} title={title}>
                {label}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-60">
              <DropdownMenuItem onSelect={() => choosePublish("test")} className="gap-2">
                <FlaskConical className="h-4 w-4 text-amber-600" />
                <span className="flex flex-col">
                  <span className="font-medium">Publish to Test</span>
                  <span className="text-xs text-muted-foreground">Its own address and demo data — the live app is not touched</span>
                </span>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => choosePublish("production")} className="gap-2">
                <Globe className="h-4 w-4 text-emerald-600" />
                <span className="flex flex-col">
                  <span className="font-medium">Publish to Production</span>
                  <span className="text-xs text-muted-foreground">Updates the live app</span>
                </span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        );
      })()}
      <Button
        variant="outline"
        size={size}
        onClick={() => {
          if (lockedMobile) { explainLock("Mobile builds"); return; }
          setInitialTab("mobile");
          setOpen(true);
        }}
        disabled={!projectId || (!isReady && !lockedMobile)}
        className="shrink-0"
        data-locked={lockedMobile ? "mobile_builds" : undefined}
        title={lockedMobile ? lockedNote("Mobile builds") : "Build a mobile app (APK / IPA)"}
        aria-label="Build mobile app"
      >
        {lockedMobile ? <Lock className="h-3.5 w-3.5" /> : <Smartphone className="h-3.5 w-3.5" />}
      </Button>
      <PublishDialog
        projectId={projectId}
        orgId={orgId}
        open={open}
        onOpenChange={setOpen}
        initialTab={initialTab}
        mobileLocked={lockedMobile}
      />
    </div>
  );
}
