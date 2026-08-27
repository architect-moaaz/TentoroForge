"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Smartphone, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { PublishDialog } from "./PublishDialog";

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
}

export function PublishButton({ projectId, orgId, size = "sm" }: Props) {
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
    refetchInterval: (q) =>
      q.state.data?.status === "generating" ? 3_000 : 30_000,
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

  const liveUrl = data?.status === "succeeded" ? data.url : null;

  return (
    <div className="flex items-center gap-1.5">
      {liveUrl && (
        <a
          href={liveUrl}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1 text-[11px] font-mono text-muted-foreground hover:text-foreground max-w-[240px] truncate"
          title={`Live at ${liveUrl}`}
        >
          <ExternalLink className="h-3 w-3 shrink-0" />
          <span className="truncate">{liveUrl.replace(/^https?:\/\//, "")}</span>
        </a>
      )}
      <Button
        variant="default"
        size={size}
        onClick={() => {
          setInitialTab("web");
          setOpen(true);
        }}
        disabled={!projectId || !isReady}
        title={
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
                    : undefined
        }
      >
        <Upload className="mr-1.5 h-3.5 w-3.5" />
        {liveUrl ? "Republish" : "Publish"}
      </Button>
      <Button
        variant="outline"
        size={size}
        onClick={() => {
          setInitialTab("mobile");
          setOpen(true);
        }}
        disabled={!projectId || !isReady}
        title="Build a mobile app (APK / IPA)"
        aria-label="Build mobile app"
      >
        <Smartphone className="h-3.5 w-3.5" />
      </Button>
      <PublishDialog
        projectId={projectId}
        orgId={orgId}
        open={open}
        onOpenChange={setOpen}
        initialTab={initialTab}
      />
    </div>
  );
}
