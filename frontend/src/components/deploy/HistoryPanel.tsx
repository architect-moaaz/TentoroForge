"use client";

/**
 * Tabbed history for a project. Two views:
 *  - Build history — every generation/version snapshot (VersionSidebar)
 *  - Deployment history — every publish attempt (DeploymentHistory)
 *
 * Rendered inside the project page under the "History" toolbar icon.
 */

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { VersionSidebar } from "@/components/projects/VersionSidebar";
import { DeploymentHistory } from "./DeploymentHistory";

interface Props {
  projectId: string;
}

export function HistoryPanel({ projectId }: Props) {
  return (
    <div className="flex h-full flex-col">
      <Tabs defaultValue="builds" className="flex h-full flex-col">
        <div className="border-b px-3 pt-2">
          <TabsList className="h-8">
            <TabsTrigger value="builds" className="text-xs">
              Build history
            </TabsTrigger>
            <TabsTrigger value="deploys" className="text-xs">
              Deployment history
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent
          value="builds"
          className="flex-1 overflow-hidden data-[state=active]:flex data-[state=active]:flex-col"
        >
          <VersionSidebar projectId={projectId} />
        </TabsContent>

        <TabsContent
          value="deploys"
          className="flex-1 overflow-y-auto data-[state=active]:block"
        >
          <DeploymentHistory projectId={projectId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
