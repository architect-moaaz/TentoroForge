"use client";

import { useEffect, useState } from "react";
import {
  Monitor,
  Tablet,
  Smartphone,
  RefreshCw,
  Play,
  Square,
  Loader2,
  ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePreview } from "@/hooks/usePreview";
import type { Project } from "@/types/project";

const DEVICE_SIZES = {
  desktop: { width: "100%", height: "100%", label: "Desktop" },
  tablet: { width: "768px", height: "100%", label: "Tablet" },
  mobile: { width: "375px", height: "100%", label: "Mobile" },
};

type Device = keyof typeof DEVICE_SIZES;

// The preview dev server is started behind a basePath of
// `/api/projects/<id>/preview/serve` (see backend/preview.py) and reached
// through the proxy at that path — never the raw dev-server port. A bare
// `http://localhost:<port>` only works when the browser and the server share a
// machine; on a hosted deploy it is the SERVER's localhost, so the iframe
// failed with "unable to connect to localhost". Route through the same origin
// the API client uses (empty on a hosted deploy → relative, so the platform's
// reverse proxy forwards it; the dev host locally).
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface PreviewFrameProps {
  projectId: string;
  project: Project | null;
}

export function PreviewFrame({ projectId, project }: PreviewFrameProps) {
  const [device, setDevice] = useState<Device>("desktop");
  const [iframeKey, setIframeKey] = useState(0);
  const { port, isStarting, error, startPreview, stopPreview, checkStatus } =
    usePreview(projectId);

  useEffect(() => {
    checkStatus();
  }, [checkStatus]);

  // Reach the dev server through the backend proxy, which fronts it at the
  // basePath the preview was started under. `port` is what tells us a preview
  // is actually running; the browser never connects to it directly.
  const previewUrl = port
    ? `${API_BASE}/api/projects/${projectId}/preview/serve/`
    : null;
  const deviceSize = DEVICE_SIZES[device];

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex items-center gap-1">
          {(
            [
              ["desktop", Monitor],
              ["tablet", Tablet],
              ["mobile", Smartphone],
            ] as const
          ).map(([key, Icon]) => (
            <Button
              key={key}
              variant={device === key ? "secondary" : "ghost"}
              size="icon"
              className="h-8 w-8"
              onClick={() => setDevice(key)}
              title={DEVICE_SIZES[key].label}
            >
              <Icon className="h-4 w-4" />
            </Button>
          ))}
        </div>

        <div className="flex items-center gap-1">
          {previewUrl && (
            <>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => setIframeKey((k) => k + 1)}
                title="Refresh"
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
              <a
                href={previewUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  title="Open in new tab"
                >
                  <ExternalLink className="h-4 w-4" />
                </Button>
              </a>
            </>
          )}

          {port ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={stopPreview}
              className="h-8 text-xs"
            >
              <Square className="mr-1 h-3 w-3" />
              Stop
            </Button>
          ) : (
            <Button
              variant="default"
              size="sm"
              onClick={startPreview}
              disabled={isStarting || project?.status === "draft"}
              className="h-8 text-xs"
            >
              {isStarting ? (
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <Play className="mr-1 h-3 w-3" />
              )}
              {isStarting ? "Starting..." : "Start Preview"}
            </Button>
          )}
        </div>
      </div>

      {/* Preview area */}
      <div className="flex flex-1 items-center justify-center overflow-hidden bg-muted/30 p-4">
        {error && (
          <p className="text-sm text-red-500">{error}</p>
        )}

        {isStarting && (
          <div className="flex flex-col items-center gap-2">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              Starting preview server...
            </p>
          </div>
        )}

        {!port && !isStarting && !error && (
          <div className="flex flex-col items-center gap-2 text-center">
            <Monitor className="h-12 w-12 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {project?.status === "draft"
                ? "Generate your app first, then preview it here"
                : "Click Start Preview to see your app"}
            </p>
          </div>
        )}

        {previewUrl && !isStarting && (
          <div
            className="overflow-hidden rounded-lg border bg-white shadow-lg"
            style={{
              width: deviceSize.width,
              height: deviceSize.height,
              maxWidth: "100%",
              maxHeight: "100%",
            }}
          >
            <iframe
              key={iframeKey}
              src={previewUrl}
              className="h-full w-full"
              title="App Preview"
            />
          </div>
        )}
      </div>
    </div>
  );
}
