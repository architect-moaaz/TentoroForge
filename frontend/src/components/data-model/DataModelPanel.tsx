"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import { useIsOrgAdmin } from "@/lib/org-admin";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  GitBranch,
  Table2,
  Terminal,
  Sprout,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useDataModelStore } from "@/stores/data-model";
import { useChatStore } from "@/stores/chat";
import { ERDCanvas } from "./ERDCanvas";
import { DatabaseBrowser } from "./DatabaseBrowser";
import { SqlConsole } from "./SqlConsole";
import { SeedDataEditor } from "./SeedDataEditor";
import { AddModelDialog } from "./AddModelDialog";
import { EditFieldDialog } from "./EditFieldDialog";
import { DeleteConfirmDialog } from "./DeleteConfirmDialog";
import { RelationshipEditor } from "./RelationshipEditor";
import { IndexEditor } from "./IndexEditor";
import { SchemaChangeProgress } from "./SchemaChangeProgress";
import { DataModelSidebar } from "./DataModelSidebar";
import type { AppModel } from "@/types/app-model";

// Same resolution as lib/api.ts — the refresh-index endpoint streams SSE, so we
// call it with a raw fetch rather than the JSON `api` client.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

type SubTab = "erd" | "browser" | "sql" | "seed";

interface DataModelPanelProps {
  projectId: string;
  dbPort?: number | null;
}

export function DataModelPanel({ projectId, dbPort }: DataModelPanelProps) {
  const params = useParams();
  const orgId = params?.orgId as string;
  const isAdmin = useIsOrgAdmin(orgId);
  const [subTab, setSubTab] = useState<SubTab>("erd");
  const [browserTable, setBrowserTable] = useState<string | null>(null);

  const handleSelectTable = useCallback((t: string) => {
    setBrowserTable(t);
    setSubTab("browser");
  }, []);

  const [showAddModel, setShowAddModel] = useState(false);
  const [editFieldTarget, setEditFieldTarget] = useState<{
    table: string;
    column?: string;
  } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{
    type: "model" | "field";
    table: string;
    field?: string;
  } | null>(null);
  const [relationTarget, setRelationTarget] = useState<string | null>(null);
  const [indexTarget, setIndexTarget] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(220);
  // BUG-013: actually run the indexer (not just re-fetch the failing endpoint).
  const [reindexing, setReindexing] = useState(false);
  const autoReindexTriedRef = useRef(false);

  const queryClient = useQueryClient();
  const { setAppModel, setLoading, setError, selectedTable, setSelectedTable } =
    useDataModelStore();
  const lastCommitHash = useChatStore((s) => s.lastCommitHash);

  const {
    data: appModel,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["project", projectId, "app-model"],
    queryFn: () => api.get<AppModel>(`/api/projects/${projectId}/app-model`),
  });

  // Sync to store
  useEffect(() => {
    if (appModel) setAppModel(appModel);
  }, [appModel, setAppModel]);

  useEffect(() => {
    setLoading(isLoading);
  }, [isLoading, setLoading]);

  // Auto-refresh when chat commits changes
  useEffect(() => {
    if (lastCommitHash) {
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "app-model"],
      });
    }
  }, [lastCommitHash, projectId, queryClient]);

  // BUG-013: the old "Re-index" button just re-ran the failing GET, so a missing
  // app-model.json never recovered. Actually POST /refresh-index (runs the
  // indexer agent, SSE), drain it to completion, then re-fetch the model.
  const handleReindex = useCallback(async () => {
    if (reindexing) return;
    setReindexing(true);
    try {
      const token =
        typeof window !== "undefined" ? localStorage.getItem("token") : null;
      const res = await fetch(
        `${API_BASE}/api/projects/${projectId}/refresh-index`,
        {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        },
      );
      // Drain the SSE stream so we wait for the indexer to finish before
      // re-fetching. We don't need per-event parsing here — stream close =
      // indexer done (or errored, in which case the re-fetch simply re-surfaces
      // the empty state).
      const reader = res.body?.getReader();
      if (reader) {
        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done } = await reader.read();
          if (done) break;
        }
      }
    } catch {
      /* swallow — the re-fetch below reflects the real state */
    } finally {
      await queryClient.invalidateQueries({
        queryKey: ["project", projectId, "app-model"],
      });
      await refetch();
      setReindexing(false);
    }
  }, [reindexing, projectId, queryClient, refetch]);

  // Auto-recover: on the first load that errors (no app-model yet), kick the
  // indexer once automatically instead of leaving the user staring at an error.
  useEffect(() => {
    if (
      !isLoading &&
      (error || !appModel) &&
      !reindexing &&
      !autoReindexTriedRef.current
    ) {
      autoReindexTriedRef.current = true;
      void handleReindex();
    }
  }, [isLoading, error, appModel, reindexing, handleReindex]);

  const handleSchemaChangeComplete = () => {
    queryClient.invalidateQueries({
      queryKey: ["project", projectId, "app-model"],
    });
    queryClient.invalidateQueries({
      queryKey: ["project", projectId, "db-tables"],
    });
    queryClient.invalidateQueries({
      queryKey: ["project", projectId, "versions"],
    });
  };

  const allSubTabs = [
    { id: "erd" as SubTab, label: "ERD", icon: GitBranch },
    { id: "browser" as SubTab, label: "Browser", icon: Table2 },
    { id: "sql" as SubTab, label: "SQL", icon: Terminal },
    { id: "seed" as SubTab, label: "Seed", icon: Sprout },
  ];
  const subTabs = isAdmin ? allSubTabs : allSubTabs.filter((t) => t.id === "erd");

  useEffect(() => {
    if (!isAdmin && subTab !== "erd") setSubTab("erd");
  }, [isAdmin]); // eslint-disable-line react-hooks/exhaustive-deps — only react to admin status changing

  if (isLoading || reindexing) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        <span className="ml-2 text-sm text-muted-foreground">
          {reindexing ? "Building the data model index…" : "Loading data model..."}
        </span>
      </div>
    );
  }

  if (error || !appModel) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <AlertCircle className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          The data model index hasn&apos;t been built yet.
        </p>
        <Button
          variant="outline"
          size="sm"
          onClick={handleReindex}
          disabled={reindexing}
        >
          <RefreshCw
            className={`mr-1 h-3 w-3 ${reindexing ? "animate-spin" : ""}`}
          />
          {reindexing ? "Indexing…" : "Build index"}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Sub-tab bar */}
      <div className="flex items-center gap-1 border-b px-3 py-1.5">
        {subTabs.map(({ id, label, icon: Icon }) => (
          <Button
            key={id}
            variant={subTab === id ? "secondary" : "ghost"}
            size="sm"
            className="h-7 text-xs"
            onClick={() => setSubTab(id)}
          >
            <Icon className="mr-1 h-3 w-3" />
            {label}
          </Button>
        ))}
      </div>

      {/* Content area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar — only for ERD sub-tab */}
        {subTab === "erd" && (
          <DataModelSidebar
            appModel={appModel}
            selectedTable={selectedTable}
            onSelectTable={(name) => setSelectedTable(name)}
            onAddModel={() => setShowAddModel(true)}
            width={sidebarWidth}
          />
        )}

        {/* Main content */}
        <div className="flex-1 overflow-hidden">
          {subTab === "erd" && (
            <ERDCanvas
              appModel={appModel}
              onAddModel={() => setShowAddModel(true)}
              onAddField={(table) =>
                setEditFieldTarget({ table })
              }
              onEditField={(table, column) =>
                setEditFieldTarget({ table, column })
              }
              onDeleteModel={(table) =>
                setDeleteTarget({ type: "model", table })
              }
              onAddIndex={(table) => setIndexTarget(table)}
              onAddRelation={(table) => setRelationTarget(table)}
              onSelectTable={isAdmin ? handleSelectTable : undefined}
            />
          )}
          {subTab === "browser" && (
            <DatabaseBrowser projectId={projectId} dbPort={dbPort} table={browserTable} />
          )}
          {subTab === "sql" && (
            <SqlConsole projectId={projectId} dbPort={dbPort} />
          )}
          {subTab === "seed" && (
            <SeedDataEditor
              projectId={projectId}
              onComplete={handleSchemaChangeComplete}
            />
          )}
        </div>
      </div>

      {/* Dialogs */}
      <AddModelDialog
        open={showAddModel}
        onOpenChange={setShowAddModel}
        projectId={projectId}
        onComplete={handleSchemaChangeComplete}
      />

      {editFieldTarget && (
        <EditFieldDialog
          open={!!editFieldTarget}
          onOpenChange={(open) => !open && setEditFieldTarget(null)}
          projectId={projectId}
          tableName={editFieldTarget.table}
          columnName={editFieldTarget.column}
          appModel={appModel}
          onComplete={handleSchemaChangeComplete}
        />
      )}

      {deleteTarget && (
        <DeleteConfirmDialog
          open={!!deleteTarget}
          onOpenChange={(open) => !open && setDeleteTarget(null)}
          projectId={projectId}
          target={deleteTarget}
          appModel={appModel}
          onComplete={handleSchemaChangeComplete}
        />
      )}

      {relationTarget && (
        <RelationshipEditor
          open={!!relationTarget}
          onOpenChange={(open) => !open && setRelationTarget(null)}
          projectId={projectId}
          sourceTable={relationTarget}
          appModel={appModel}
          onComplete={handleSchemaChangeComplete}
        />
      )}

      {indexTarget && (
        <IndexEditor
          open={!!indexTarget}
          onOpenChange={(open) => !open && setIndexTarget(null)}
          projectId={projectId}
          tableName={indexTarget}
          appModel={appModel}
          onComplete={handleSchemaChangeComplete}
        />
      )}
    </div>
  );
}
