"use client";

import { useState, useCallback, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Save,
  Play,
  Loader2,
  Map,
  Package,
  Plus,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useNavigationStore } from "@/stores/navigation";
import { NavigationEditor } from "./NavigationEditor";
import { ScreenProperties } from "./ScreenProperties";
import { ModuleManager } from "./ModuleManager";
import { ModuleWizard } from "./ModuleWizard";
import type {
  ScreenNodeSerialized,
  NavEdgeSerialized,
  ScreenNodeData,
  NavigationConfig,
} from "@/types/navigation";

interface NavigationPanelProps {
  projectId: string;
}

export function NavigationPanel({ projectId }: NavigationPanelProps) {
  const queryClient = useQueryClient();
  const {
    screens,
    setScreens,
    edges,
    setEdges,
    sidebarLinks,
    setSidebarLinks,
    topbarLinks,
    setTopbarLinks,
    selectedScreenId,
    setSelectedScreenId,
    activeSubTab,
    setActiveSubTab,
  } = useNavigationStore();

  const [isSaving, setIsSaving] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [applyStatus, setApplyStatus] = useState<string | null>(null);

  // Load navigation config
  const { data: navData, isLoading } = useQuery({
    queryKey: ["project", projectId, "navigation"],
    queryFn: () =>
      api.get<{
        screens: ScreenNodeSerialized[];
        edges: NavEdgeSerialized[];
        sidebarLinks: unknown[];
        topbarLinks: unknown[];
        defaultScreen?: string;
        errorScreen?: string;
      }>(`/api/projects/${projectId}/navigation`),
  });

  // Load modules layout (file-based, for canvas positions)
  const { data: moduleData } = useQuery({
    queryKey: ["project", projectId, "modules-layout"],
    queryFn: () =>
      api.get<{ modules: unknown[]; dependencies: unknown[] }>(
        `/api/projects/${projectId}/modules/layout`,
      ),
  });

  useEffect(() => {
    if (navData) {
      setScreens(navData.screens || []);
      setEdges(navData.edges || []);
    }
  }, [navData, setScreens, setEdges]);

  // Save
  const save = useCallback(async () => {
    setIsSaving(true);
    await api.post(`/api/projects/${projectId}/navigation`, {
      screens,
      edges,
      sidebarLinks,
      topbarLinks,
    });
    queryClient.invalidateQueries({
      queryKey: ["project", projectId, "navigation"],
    });
    setIsSaving(false);
  }, [screens, edges, sidebarLinks, topbarLinks, projectId, queryClient]);

  // Apply
  const apply = useCallback(async () => {
    await save();
    setIsApplying(true);
    setApplyStatus("Applying navigation...");

    const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
    const token =
      typeof window !== "undefined" ? localStorage.getItem("token") : null;

    const response = await fetch(
      `${API_BASE}/api/projects/${projectId}/navigation/apply`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      },
    );

    if (response.ok && response.body) {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data:")) {
            try {
              const data = JSON.parse(line.slice(5));
              if (data.message) setApplyStatus(data.message);
            } catch {}
          }
        }
      }
    }

    setIsApplying(false);
    setApplyStatus(null);
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });
  }, [save, projectId, queryClient]);

  // Add new screen
  const addScreen = useCallback(() => {
    const id = `screen_${Date.now()}`;
    const newScreen: ScreenNodeSerialized = {
      id,
      type: "screen",
      position: { x: 100 + Math.random() * 200, y: 100 + Math.random() * 200 },
      data: {
        label: "New Screen",
        route: "/new-screen",
        layout: "sidebar",
      },
    };
    setScreens([...screens, newScreen]);
  }, [screens, setScreens]);

  // Update screen data
  const updateScreenData = useCallback(
    (updates: Partial<ScreenNodeData>) => {
      if (!selectedScreenId) return;
      setScreens(
        screens.map((s) =>
          s.id === selectedScreenId
            ? { ...s, data: { ...s.data, ...updates } }
            : s,
        ),
      );
    },
    [selectedScreenId, screens, setScreens],
  );

  const setDefault = useCallback(() => {
    if (!selectedScreenId) return;
    setScreens(
      screens.map((s) => ({
        ...s,
        data: { ...s.data, isDefault: s.id === selectedScreenId },
      })),
    );
  }, [selectedScreenId, screens, setScreens]);

  const setError = useCallback(() => {
    if (!selectedScreenId) return;
    setScreens(
      screens.map((s) => ({
        ...s,
        data: { ...s.data, isError: s.id === selectedScreenId },
      })),
    );
  }, [selectedScreenId, screens, setScreens]);

  const selectedScreen = selectedScreenId
    ? screens.find((s) => s.id === selectedScreenId)
    : null;

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <div className="flex items-center gap-0.5 rounded-md border p-0.5">
          <Button
            variant={activeSubTab === "screens" ? "secondary" : "ghost"}
            size="sm"
            className="h-7 text-xs"
            onClick={() => setActiveSubTab("screens")}
          >
            <Map className="mr-1 h-3.5 w-3.5" />
            Screens
          </Button>
          <Button
            variant={activeSubTab === "modules" ? "secondary" : "ghost"}
            size="sm"
            className="h-7 text-xs"
            onClick={() => setActiveSubTab("modules")}
          >
            <Package className="mr-1 h-3.5 w-3.5" />
            Modules
          </Button>
        </div>

        <div className="flex-1" />

        {activeSubTab === "screens" && (
          <Button size="sm" variant="outline" onClick={addScreen}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            Add Screen
          </Button>
        )}

        <Button size="sm" variant="outline" onClick={save} disabled={isSaving}>
          {isSaving ? (
            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="mr-1 h-3.5 w-3.5" />
          )}
          Save
        </Button>
        <Button size="sm" onClick={apply} disabled={isApplying}>
          {isApplying ? (
            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="mr-1 h-3.5 w-3.5" />
          )}
          Apply
        </Button>
      </div>

      {/* Status bar */}
      {applyStatus && (
        <div className="border-b bg-blue-50 px-4 py-1.5">
          <p className="text-xs text-blue-700">{applyStatus}</p>
        </div>
      )}

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {activeSubTab === "screens" ? (
          <>
            <div className="flex-1">
              {isLoading ? (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <NavigationEditor
                  initialScreens={screens}
                  initialEdges={edges}
                  onScreensChange={setScreens}
                  onEdgesChange={setEdges}
                />
              )}
            </div>
            {selectedScreen && (
              <ScreenProperties
                data={selectedScreen.data}
                onUpdate={updateScreenData}
                onClose={() => setSelectedScreenId(null)}
                onSetDefault={setDefault}
                onSetError={setError}
              />
            )}
          </>
        ) : (
          <div className="flex-1 overflow-y-auto">
            <ModuleWizard projectId={projectId} />
          </div>
        )}
      </div>
    </div>
  );
}
