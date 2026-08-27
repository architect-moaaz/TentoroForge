"use client";

/**
 * MOBILE-D — Mobile-app tab body inside the Publish dialog.
 *
 * Two action rows (Android + iOS), each with:
 *   * a "Preview build" button (internal-distribution APK / device IPA /
 *     sim IPA) — a downloadable file for local + UAT testing
 *   * a "Store build" button (Play Store AAB / App Store IPA) — signed,
 *     store-submittable
 *
 * Below that, a history list of past builds with status, artifact
 * download link, and logs link. The list polls every 6 s while any
 * build is still in a non-terminal state so the UI stays live without
 * a websocket.
 *
 * Missing-credentials failures from the backend return a structured
 * error `{missing_keys, action: "add_credentials"}` — we surface a
 * one-tap link to the org's Settings → Integrations page instead of a
 * raw error string, so the user's next step is obvious.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  Apple,
  CheckCircle2,
  Cog,
  Download,
  ExternalLink,
  Loader2,
  Smartphone,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth";
import { toast } from "sonner";

interface MobileBuild {
  id: string;
  project_id: string;
  profile: string;
  platform: string;
  status: string; // pending | in_progress | completed | failed | canceled
  eas_build_id: string | null;
  artifact_url: string | null;
  logs_url: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

interface Props {
  projectId: string;
  /** Slug of the org the project belongs to — used to link to
   *  /org/[orgId]/settings/integrations when credentials are missing. */
  orgId: string;
}

// Poll cadence while at least one build is non-terminal.
const POLL_INTERVAL_MS = 6000;

function isTerminal(status: string): boolean {
  return ["completed", "failed", "canceled"].includes(status);
}

function statusLabel(status: string): string {
  switch (status) {
    case "pending":     return "Queued";
    case "in_progress": return "Building";
    case "completed":   return "Ready";
    case "failed":      return "Failed";
    case "canceled":    return "Canceled";
    default:            return status;
  }
}

function StatusIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />;
  if (status === "failed" || status === "canceled")
    return <XCircle className="h-3.5 w-3.5 text-red-500" />;
  return <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />;
}

export function MobileBuildsPanel({ projectId, orgId }: Props) {
  const token = useAuthStore((s) => s.token);
  const [builds, setBuilds] = useState<MobileBuild[]>([]);
  const [loading, setLoading] = useState<null | { profile: string; platform: string }>(null);
  const [error, setError] = useState<{ message: string; missing_keys?: string[]; action?: string } | null>(null);
  const mounted = useRef(true);

  useEffect(() => () => { mounted.current = false; }, []);

  const authHeaders = useMemo<Record<string, string>>(() => (
    token ? { Authorization: `Bearer ${token}` } : {}
  ), [token]);

  const fetchList = useCallback(async () => {
    try {
      const res = await fetch(`/api/projects/${projectId}/mobile-builds`, {
        headers: authHeaders,
      });
      if (!res.ok) return;
      const data = (await res.json()) as MobileBuild[];
      if (mounted.current) setBuilds(data);
    } catch {
      // Silent — this runs on a poll cadence, one hiccup shouldn't nag.
    }
  }, [projectId, authHeaders]);

  // Initial load + poll while any build is non-terminal.
  useEffect(() => {
    void fetchList();
  }, [fetchList]);

  useEffect(() => {
    const anyLive = builds.some((b) => !isTerminal(b.status));
    if (!anyLive) return;
    const id = setInterval(() => void fetchList(), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [builds, fetchList]);

  const startBuild = useCallback(
    async (profile: "preview" | "production", platform: "android" | "ios") => {
      setLoading({ profile, platform });
      setError(null);
      try {
        const res = await fetch(`/api/projects/${projectId}/mobile-builds`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...authHeaders,
          },
          body: JSON.stringify({ profile, platform }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          const detail = body?.detail;
          if (typeof detail === "object" && detail !== null) {
            setError({
              message: (detail as any).message ?? "Build failed to start.",
              missing_keys: (detail as any).missing_keys,
              action: (detail as any).action,
            });
          } else {
            setError({ message: typeof detail === "string" ? detail : `HTTP ${res.status}` });
          }
          return;
        }
        toast.success(`${platform === "ios" ? "iOS" : "Android"} build queued`);
        await fetchList();
      } catch (e) {
        setError({ message: e instanceof Error ? e.message : String(e) });
      } finally {
        if (mounted.current) setLoading(null);
      }
    },
    [projectId, authHeaders, fetchList],
  );

  const settingsHref = `/org/${orgId}/settings/integrations`;

  return (
    <div className="space-y-4">
      {/* Two action rows */}
      <div className="space-y-2">
        <PlatformRow
          icon={<Smartphone className="h-4 w-4" />}
          title="Android"
          onPreview={() => void startBuild("preview", "android")}
          onProduction={() => void startBuild("production", "android")}
          loading={loading?.platform === "android" ? loading.profile : null}
        />
        <PlatformRow
          icon={<Apple className="h-4 w-4" />}
          title="iOS"
          onPreview={() => void startBuild("preview", "ios")}
          onProduction={() => void startBuild("production", "ios")}
          loading={loading?.platform === "ios" ? loading.profile : null}
        />
      </div>

      {/* Structured error surface */}
      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-900 space-y-2">
          <div className="flex items-start gap-2">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <div className="flex-1 leading-snug">{error.message}</div>
          </div>
          {error.action === "add_credentials" && (
            <div className="ml-6 space-y-2">
              {error.missing_keys && error.missing_keys.length > 0 && (
                <div className="text-[11px] font-mono opacity-70">
                  Missing: {error.missing_keys.join(", ")}
                </div>
              )}
              <Link
                href={settingsHref}
                className="inline-flex items-center gap-1 text-xs font-medium text-red-900 hover:underline"
              >
                <Cog className="h-3 w-3" />
                Open Integrations settings
              </Link>
            </div>
          )}
        </div>
      )}

      {/* History */}
      <div className="space-y-1.5">
        <div className="text-xs font-medium text-muted-foreground">
          Recent builds
        </div>
        {builds.length === 0 && (
          <div className="rounded border bg-muted/40 px-3 py-4 text-xs text-muted-foreground text-center">
            No mobile builds yet. Pick a target above to start one.
          </div>
        )}
        {builds.map((b) => (
          <BuildRow key={b.id} build={b} />
        ))}
      </div>

      <div className="text-[11px] text-muted-foreground leading-snug">
        Builds run on Expo EAS ({" "}
        <Link
          href={settingsHref}
          className="underline underline-offset-2 hover:text-foreground"
        >
          manage credentials
        </Link>
        ). Store builds require an Apple Developer + Google Play account.
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Platform row — the two action buttons for one OS                            //
// --------------------------------------------------------------------------- //

function PlatformRow({
  icon,
  title,
  onPreview,
  onProduction,
  loading,
}: {
  icon: React.ReactNode;
  title: string;
  onPreview: () => void;
  onProduction: () => void;
  loading: string | null;
}) {
  return (
    <div className="rounded border bg-background p-3 flex items-center gap-3">
      <div className="flex items-center gap-2 min-w-[80px]">
        {icon}
        <span className="text-sm font-medium">{title}</span>
      </div>
      <div className="flex-1" />
      <Button
        variant="outline"
        size="sm"
        disabled={loading !== null}
        onClick={onPreview}
        className="h-7 text-xs"
      >
        {loading === "preview" ? (
          <Loader2 className="h-3 w-3 animate-spin mr-1" />
        ) : null}
        Preview build
      </Button>
      <Button
        size="sm"
        disabled={loading !== null}
        onClick={onProduction}
        className="h-7 text-xs"
      >
        {loading === "production" ? (
          <Loader2 className="h-3 w-3 animate-spin mr-1" />
        ) : null}
        Store build
      </Button>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Build row — one entry in the history list                                   //
// --------------------------------------------------------------------------- //

function BuildRow({ build }: { build: MobileBuild }) {
  const created = new Date(build.created_at);
  const timeStr = created.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  const iconForPlatform = build.platform === "ios"
    ? <Apple className="h-3 w-3" />
    : <Smartphone className="h-3 w-3" />;
  return (
    <div className="rounded border bg-background px-3 py-2 flex items-center gap-2 text-xs">
      <StatusIcon status={build.status} />
      <div className="flex items-center gap-1 min-w-[64px]">
        {iconForPlatform}
        <span className="capitalize">{build.platform}</span>
      </div>
      <div className="min-w-[64px] text-muted-foreground capitalize">
        {build.profile.replace("-", " ")}
      </div>
      <div className="min-w-[56px]">{statusLabel(build.status)}</div>
      <div className="flex-1 text-muted-foreground">{timeStr}</div>
      {build.artifact_url && build.status === "completed" && (
        <a
          href={build.artifact_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-primary hover:underline"
        >
          <Download className="h-3 w-3" />
          Download
        </a>
      )}
      {build.logs_url && (
        <a
          href={build.logs_url}
          target="_blank"
          rel="noreferrer"
          className="text-muted-foreground hover:text-foreground"
          title="Open EAS logs"
        >
          <ExternalLink className="h-3 w-3" />
        </a>
      )}
      {build.status === "failed" && build.error_message && (
        <span
          className="text-red-600 max-w-[200px] truncate"
          title={build.error_message}
        >
          {build.error_message}
        </span>
      )}
    </div>
  );
}
