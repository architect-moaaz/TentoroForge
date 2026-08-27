"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  MessageSquare,
  Eye,
  Code,
  ChevronLeft,
  Loader2,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import type { Project } from "@/types/project";
import { Badge } from "@/components/ui/badge";

function ProjectLayout({
  children,
  orgId,
  projectId,
}: {
  children: React.ReactNode;
  orgId: string;
  projectId: string;
}) {
  const { data: project, isLoading } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.get<Project>(`/api/projects/${projectId}`),
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Top bar */}
      <header className="flex items-center gap-3 border-b px-4 py-2">
        <Link href={`/org/${orgId}/projects`}>
          <Button variant="ghost" size="icon" className="h-8 w-8">
            <ChevronLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold">
            {project?.name || "Project"}
          </h1>
        </div>
        {project && (
          <Badge variant="outline" className="text-xs">
            {project.status}
          </Badge>
        )}
      </header>

      {/* Content */}
      <div className="flex-1 overflow-hidden">{children}</div>
    </div>
  );
}

export default function ProjectLayoutWrapper({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ orgId: string; projectId: string }>;
}) {
  const { orgId, projectId } = use(params);
  return (
    <ProjectLayout orgId={orgId} projectId={projectId}>
      {children}
    </ProjectLayout>
  );
}
