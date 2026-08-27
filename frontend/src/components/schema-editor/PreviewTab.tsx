"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Loader2,
  Image as ImageIcon,
  Smartphone,
  Tablet,
  Monitor,
} from "lucide-react";
import { useState } from "react";
import { renderPage } from "@/lib/render-service-client";

type Viewport = "mobile" | "tablet" | "desktop";

interface PreviewTabProps {
  /** The project short_id (e.g. "7zn274s3") */
  projectId: string;
  /** The page route to render, e.g. "/users/list" */
  pageRoute: string;
}

export function PreviewTab({ projectId, pageRoute }: PreviewTabProps) {
  const [viewport, setViewport] = useState<Viewport>("desktop");

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["render", projectId, pageRoute, viewport],
    queryFn: () => renderPage(projectId, pageRoute, viewport),
    staleTime: 60_000,
    enabled: !!pageRoute,
  });

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-2 border-b px-4 py-2 shrink-0">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Preview
        </span>
        <code className="ml-1 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
          {pageRoute || "—"}
        </code>
        <div className="ml-auto flex items-center gap-1">
          {(
            [
              { v: "mobile" as Viewport, Icon: Smartphone, label: "Mobile" },
              { v: "tablet" as Viewport, Icon: Tablet, label: "Tablet" },
              { v: "desktop" as Viewport, Icon: Monitor, label: "Desktop" },
            ] as const
          ).map(({ v, Icon, label }) => (
            <button
              key={v}
              type="button"
              onClick={() => setViewport(v)}
              title={label}
              className={`flex h-7 w-7 items-center justify-center rounded transition-colors ${
                viewport === v
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:bg-muted/50"
              }`}
            >
              <Icon className="h-4 w-4" />
            </button>
          ))}
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="ml-2 rounded border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto bg-muted/30 p-4">
        {(isLoading || isFetching) && (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            <span className="text-sm">Rendering…</span>
          </div>
        )}

        {!isFetching && error && (
          <div className="text-sm text-destructive">Render service error.</div>
        )}

        {!isFetching && data && (
          <div className="flex justify-center">
            <img
              alt={`Render of ${pageRoute}`}
              src={`data:image/png;base64,${data.pngBase64}`}
              className="max-w-full rounded shadow"
            />
          </div>
        )}

        {!isFetching && !error && data === null && (
          <div className="flex h-full flex-col items-center justify-center text-sm text-muted-foreground">
            <ImageIcon className="mb-2 h-6 w-6" />
            <span>Render service unreachable.</span>
            <span className="mt-1">
              Start it with{" "}
              <code className="rounded bg-muted px-1">
                python -m services.render_service
              </code>
              .
            </span>
          </div>
        )}

        {!isFetching && !error && data === undefined && !pageRoute && (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            No page selected. Pick a page above to preview it.
          </div>
        )}
      </div>
    </div>
  );
}
