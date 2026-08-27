"use client";

import { useQuery } from "@tanstack/react-query";
import { GitCommit, Clock } from "lucide-react";
import { api } from "@/lib/api";
import type { Version } from "@/types/project";

interface VersionSidebarProps {
  projectId: string;
}

export function VersionSidebar({ projectId }: VersionSidebarProps) {
  const { data: versions, isLoading } = useQuery({
    queryKey: ["project", projectId, "versions"],
    queryFn: () => api.get<Version[]>(`/api/projects/${projectId}/versions`),
    refetchInterval: 10000,
  });

  if (isLoading) {
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
