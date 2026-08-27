"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, FileWarning, FileJson, Image, BarChart2 } from "lucide-react";
import { api } from "@/lib/api";
import { fetchFidelityLog, type FidelityLog } from "@/lib/fidelity-client";
import { EditorMount } from "./EditorMount";
import { PreviewTab } from "./PreviewTab";
import { CritiquePanel } from "./CritiquePanel";
import { PageScoreBadge } from "./PageScoreBadge";
import type { Project } from "@/types/project";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

type SubTab = "editor" | "preview" | "score";

interface SchemaEditorPanelProps {
  projectId: string;
}

interface AppModelPage {
  path: string;
  component: string;
}

interface AppModel {
  pages?: AppModelPage[];
}

/**
 * Project-workspace tab wrapper around the schema-driven Editor.
 *
 * Three sub-tabs:
 *  - Editor  — the AHTML schema editor (EditorMount)
 *  - Preview — live screenshot from the render-service (port 6502)
 *  - Score   — fidelity critique from the backend scoring endpoint
 */
export function SchemaEditorPanel({ projectId }: SchemaEditorPanelProps) {
  const [activeSubTab, setActiveSubTab] = useState<SubTab>("editor");
  const [selectedPageRoute, setSelectedPageRoute] = useState<string>("");
  const [fidelityLog, setFidelityLog] = useState<FidelityLog | null>(null);
  const [activeRegister, setActiveRegister] = useState<string>("default");
  const [registerMenuOpen, setRegisterMenuOpen] = useState(false);

  const REGISTERS = ["default", "workday", "linear", "stripe", "notion", "figma"] as const;

  async function handleRegisterChange(newRegister: string) {
    if (!project?.short_id || newRegister === activeRegister) {
      setRegisterMenuOpen(false);
      return;
    }
    try {
      const r = await fetch(`${API_BASE}/api/_debug/project-register/${project.short_id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ register: newRegister }),
      });
      if (r.ok) setActiveRegister(newRegister);
    } catch {
      // Silently ignore — badge stays at previous value
    }
    setRegisterMenuOpen(false);
  }

  const {
    data: project,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.get<Project>(`/api/projects/${projectId}`),
  });

  // Fetch app-model pages so Preview + Score know which routes exist.
  // Only runs once the project has loaded (short_id needed to confirm it's ready).
  const { data: appModel } = useQuery({
    queryKey: ["project", projectId, "app-model"],
    queryFn: () => api.get<AppModel>(`/api/projects/${projectId}/app-model`),
    enabled: !!project?.short_id,
    staleTime: 60_000,
  });

  // Fetch fidelity log when the project short_id is available.
  useEffect(() => {
    if (!project?.short_id) return;
    let cancelled = false;
    fetchFidelityLog(project.short_id).then((log) => {
      if (!cancelled) setFidelityLog(log);
    });
    return () => {
      cancelled = true;
    };
  }, [project?.short_id]);

  // Fetch the active design register from design-spec.json.
  useEffect(() => {
    if (!project?.short_id) return;
    let cancelled = false;
    fetch(
      `${API_BASE}/api/_debug/project-file/${project.short_id}/src/contracts/design-spec.json`,
    )
      .then((r) => (r.ok ? r.json() : {}))
      .then((spec) => {
        if (!cancelled) setActiveRegister((spec as { register?: string })?.register || "default");
      })
      .catch(() => {
        if (!cancelled) setActiveRegister("default");
      });
    return () => {
      cancelled = true;
    };
  }, [project?.short_id]);

  // Pick the first available page as default when app-model loads.
  const pages: AppModelPage[] = appModel?.pages ?? [];
  const effectiveRoute =
    selectedPageRoute || pages[0]?.path || "";

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        <span className="text-sm">Loading project…</span>
      </div>
    );
  }

  if (error || !project?.short_id) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex max-w-md items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <FileWarning className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">Schema editor unavailable</p>
            <p className="mt-1 text-xs">
              This project has no <code>short_id</code> yet. Schemas are
              generated during the build pipeline — try again once generation
              completes.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const shortId = project.short_id;

  // Context for fidelity scoring — derived from project fields where possible.
  const critiqueContext = {
    domain: "general",
    appName: project.name,
    description: project.description ?? "",
    tone: "professional",
  };

  return (
    <div className="h-full flex flex-col bg-background">
      {/* Sub-tab bar */}
      <div className="flex items-center gap-0 border-b bg-background shrink-0">
        {(
          [
            { id: "editor" as SubTab, label: "Editor", Icon: FileJson },
            { id: "preview" as SubTab, label: "Preview", Icon: Image },
            { id: "score" as SubTab, label: "Score", Icon: BarChart2 },
          ] as const
        ).map(({ id, label, Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setActiveSubTab(id)}
            className={`flex items-center gap-1.5 px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
              activeSubTab === id
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground"
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}

        {/* Register dropdown — click to override active register */}
        <div className="relative ml-3">
          <button
            type="button"
            onClick={() => setRegisterMenuOpen((v) => !v)}
            className="rounded-full border border-border bg-muted/50 px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground hover:bg-muted/80"
            title="Click to switch design register"
          >
            {activeRegister === "default" ? "default register" : `${activeRegister}-tier`}
            <span className="ml-1 opacity-60">▾</span>
          </button>
          {registerMenuOpen && (
            <div className="absolute left-0 top-full mt-1 w-44 rounded-md border border-border bg-popover py-1 text-xs shadow-lg z-10">
              {REGISTERS.map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => handleRegisterChange(r)}
                  className={`block w-full text-left px-3 py-1.5 hover:bg-muted ${r === activeRegister ? "font-semibold text-foreground" : "text-muted-foreground"}`}
                >
                  {r === "default" ? "default" : `${r}-tier`}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Page picker — shown on Preview and Score tabs */}
        {activeSubTab !== "editor" && pages.length > 0 && (
          <div className="ml-auto flex items-center gap-2 px-3">
            <span className="text-[11px] text-muted-foreground">Page:</span>
            <select
              value={selectedPageRoute || pages[0]?.path || ""}
              onChange={(e) => setSelectedPageRoute(e.target.value)}
              className="rounded border bg-background px-1.5 py-0.5 text-xs text-foreground focus:outline-none"
            >
              {pages.map((p) => {
                const entry = fidelityLog?.[p.path];
                const scoreLabel =
                  entry?.exit_status === "budget"
                    ? " (skip)"
                    : entry?.final_score != null
                      ? ` (${entry.final_score.toFixed(1)})`
                      : "";
                return (
                  <option key={p.path} value={p.path}>
                    {p.path}{scoreLabel}
                  </option>
                );
              })}
            </select>
          </div>
        )}
      </div>

      {/* Page score strip — shown in editor tab when fidelity data is available */}
      {activeSubTab === "editor" && fidelityLog && pages.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b bg-muted/30 px-3 py-1.5 shrink-0">
          <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Fidelity:
          </span>
          {pages.map((p) => {
            const entry = fidelityLog[p.path];
            return (
              <div key={p.path} className="flex items-center gap-1">
                <span className="text-[11px] text-muted-foreground">{p.path}</span>
                <PageScoreBadge
                  score={entry?.final_score ?? null}
                  failedFidelity={entry?.failed_fidelity}
                  exitStatus={entry?.exit_status}
                />
              </div>
            );
          })}
        </div>
      )}

      {/* Sub-tab content */}
      <div className="flex-1 overflow-hidden">
        {activeSubTab === "editor" && (
          <EditorMount projectId={shortId} schemaPath="" />
        )}

        {activeSubTab === "preview" && (
          <PreviewTab projectId={shortId} pageRoute={effectiveRoute} />
        )}

        {activeSubTab === "score" && (
          <CritiquePanel
            shortId={shortId}
            pageRoute={effectiveRoute}
            pagePath={effectiveRoute}
            context={critiqueContext}
          />
        )}
      </div>
    </div>
  );
}
