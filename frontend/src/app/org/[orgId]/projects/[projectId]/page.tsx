"use client";

import { use, useState, useEffect, useMemo, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  MessageSquare,
  Eye,
  Code,
  GitBranch,
  Database,
  Shield,
  Workflow,
  PaintBucket,
  Map,
  Bot,
  Sparkles,
  Download,
  Trash2,
  BarChart3,
  Table2,
  Building2,
  ChevronLeft,
  Layers,
  Layout,
  KeyRound,
  Scale,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
// §112 — Smith is the conversation in this workspace. `ChatPanel` drives
// routers/generate.py, which never imports services.blueprint, so the chat
// people actually used could not reach the Blueprint engine at all.
import { SmithPanel } from "@/components/smith/SmithPanel";
import { PreviewFrame } from "@/components/preview/PreviewFrame";
import { CodePanel } from "@/components/code/CodePanel";
import { HistoryPanel } from "@/components/deploy/HistoryPanel";
import { DataModelPanel } from "@/components/data-model/DataModelPanel";
import { RulesPanel } from "@/components/rules/RulesPanel";
import { WorkflowPanel } from "@/components/workflow/WorkflowPanel";
import { VisualEditor } from "@/components/visual-editor/VisualEditor";
import { IREditor } from "@/components/ir-editor/IREditor";
import { DesignEditor } from "@/components/design-editor/DesignEditor";
import { VisualEditorWorkspace } from "@/components/visual-editor/VisualEditorWorkspace";
import { NavigationPanel } from "@/components/navigation/NavigationPanel";
import { AgentBuilderPanel } from "@/components/agent-builder/AgentBuilderPanel";
import { AIFeaturesPanel } from "@/components/ai-features/AIFeaturesPanel";
import { CostTrackingPanel } from "@/components/monitoring/CostTrackingPanel";
import { DRDEditorPanel } from "@/components/decision/DRDEditorPanel";
import { BusinessRulesPanel } from "@/components/business-rules/BusinessRulesPanel";
import { ExportDialog } from "@/components/projects/ExportDialog";
import { PublishButton } from "@/components/deploy/PublishButton";
import { DeleteProjectDialog } from "@/components/projects/DeleteProjectDialog";
import { CommandPalette } from "@/components/CommandPalette";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useChatStore } from "@/stores/chat";
import { VirtualOffice } from "@/components/virtual-office";
import type { Project, ChatMessage } from "@/types/project";
import type { CommandItem } from "@/types/portal";

type Tab = "chat" | "preview" | "code" | "data" | "rules" | "business-rules" | "decisions" | "workflows" | "editor" | "design" | "design-editor" | "ir-editor" | "navigation" | "agents" | "ai" | "monitoring" | "versions" | "office";

// Tooltip component — positioned to the right of the icon
function Tooltip({ children, label, shortcut }: { children: React.ReactNode; label: string; shortcut?: string }) {
  return (
    <div className="group/tip relative">
      {children}
      <div className="pointer-events-none absolute left-full ml-2 top-1/2 -translate-y-1/2 z-50 opacity-0 group-hover/tip:opacity-100 transition-opacity duration-150">
        <div className="flex items-center gap-2 whitespace-nowrap rounded-md bg-slate-900 px-2.5 py-1.5 text-xs text-white shadow-lg dark:bg-white dark:text-slate-900">
          {label}
          {shortcut && <kbd className="rounded bg-slate-700 px-1 py-0.5 text-[10px] font-mono text-slate-300 dark:bg-slate-200 dark:text-slate-600">{shortcut}</kbd>}
        </div>
      </div>
    </div>
  );
}

function ProjectWorkspace({
  orgId,
  projectId,
}: {
  orgId: string;
  projectId: string;
}) {
  const [activeTab, setActiveTab] = useState<Tab>("chat");
  const [showExport, setShowExport] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [showCommandPalette, setShowCommandPalette] = useState(false);

  // POST /api/projects/{id}/integrations/sync — rewrites .env.local from
  // the platform integrations store. Response: {written, set, cleared, skipped}.
  const syncIntegrations = useMutation({
    mutationFn: () => api.post<{
      written: boolean;
      set: string[];
      cleared: string[];
      skipped: { key: string; reason: string }[];
    }>(`/api/projects/${projectId}/integrations/sync`, {}),
    onSuccess: (r) => {
      const parts: string[] = [];
      if (r.set.length) parts.push(`${r.set.length} set`);
      if (r.cleared.length) parts.push(`${r.cleared.length} cleared`);
      if (!parts.length) parts.push("no changes");
      const msg = `Synced .env.local — ${parts.join(", ")}. ${r.written ? "File rewritten." : "Already up to date."}`;
      if (r.skipped?.length) {
        toast.warning(`${msg} Skipped: ${r.skipped.map((s) => s.key).join(", ")}`);
      } else {
        toast.success(msg);
      }
    },
    onError: (err: any) => {
      toast.error(`Sync failed: ${err?.message ?? "unknown error"}`);
    },
  });
  // Shared page route between Design Editor and Visual Editor
  const [activeDesignRoute, setActiveDesignRoute] = useState<string | undefined>(undefined);
  const queryClient = useQueryClient();
  const router = useRouter();
  const { setMessages, reset: resetChat } = useChatStore();
  const lastIntent = useChatStore((s) => s.lastIntent);

  // Reset chat + office store on every projectId change AND on first mount.
  // Ref starts null so the initial-mount guard fires — otherwise
  // useRef(projectId) initialized to the new project's id makes the guard
  // false, and the zustand singleton keeps the previous project's messages
  // visible until the (possibly slow or empty) history query arrives.
  const prevProjectIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (prevProjectIdRef.current !== projectId) {
      prevProjectIdRef.current = projectId;
      resetChat();
    }
  }, [projectId, resetChat]);

  // Keyboard shortcuts
  useKeyboardShortcuts([
    {
      key: "k",
      meta: true,
      action: () => setShowCommandPalette((v) => !v),
      description: "Toggle command palette",
    },
    {
      key: "1",
      meta: true,
      action: () => setActiveTab("chat"),
      description: "Switch to Chat",
    },
    {
      key: "2",
      meta: true,
      action: () => setActiveTab("preview"),
      description: "Switch to Preview",
    },
    {
      key: "3",
      meta: true,
      action: () => setActiveTab("code"),
      description: "Switch to Code",
    },
  ]);

  // Auto-switch tabs when NAVIGATE intent fires
  useEffect(() => {
    if (lastIntent === "NAVIGATE") {
      setActiveTab("data");
    } else if (lastIntent === "NAVIGATE_RULES") {
      setActiveTab("rules");
    } else if (lastIntent === "NAVIGATE_DECISIONS") {
      setActiveTab("decisions");
    } else if (lastIntent === "NAVIGATE_WORKFLOWS") {
      setActiveTab("workflows");
    } else if (lastIntent === "NAVIGATE_AGENTS") {
      setActiveTab("agents");
    } else if (lastIntent === "NAVIGATE_AI") {
      setActiveTab("ai");
    }
  }, [lastIntent]);

  const { data: project } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.get<Project>(`/api/projects/${projectId}`),
  });

  // §25/§109 — what Smith understood, so the approval gate can show it.
  //
  // SmithPanel renders the Application Definition from this prop and nothing
  // else; without it the gate offered "Approve and build" above a stage list
  // and a tick per node, so the one thing being approved was the one thing
  // not on screen. `/blueprint/[projectId]` had always passed it and this
  // call site — the chat tab people actually use — never did.
  //
  // A project with no Blueprint yet answers 404, which is the ordinary state
  // before the first define run rather than an error worth surfacing.
  const { data: blueprintDoc } = useQuery({
    queryKey: ["project", projectId, "blueprint"],
    queryFn: () =>
      api.get<Record<string, unknown>>(`/api/projects/${projectId}/blueprint`),
    retry: false,
  });

  // Load conversation history
  const { data: history } = useQuery({
    queryKey: ["project", projectId, "conversations"],
    queryFn: () =>
      api.get<ChatMessage[]>(`/api/projects/${projectId}/conversations`),
  });

  useEffect(() => {
    // Don't overwrite chat store while streaming — it would wipe
    // the optimistic user message and in-progress assistant response
    if (history && !useChatStore.getState().isGenerating) {
      setMessages(history);
    }
  }, [history, setMessages]);

  // Visible tabs — streamlined from 16 to 9, grouped logically
  const tabs = [
    { id: "chat" as Tab, label: "Chat", icon: MessageSquare },
    { id: "preview" as Tab, label: "Preview", icon: Eye },
    { id: "code" as Tab, label: "Code", icon: Code },
    { id: "data" as Tab, label: "Data", icon: Database },
    { id: "rules" as Tab, label: "Rules", icon: Shield },
    { id: "business-rules" as Tab, label: "Business Rules", icon: Scale },
    { id: "decisions" as Tab, label: "Decisions", icon: Table2 },
    { id: "workflows" as Tab, label: "Workflows", icon: Workflow },
    { id: "design" as Tab, label: "Design", icon: PaintBucket },
    { id: "design-editor" as Tab, label: "AHTML Editor", icon: Table2 },
    { id: "ir-editor" as Tab, label: "IR Editor", icon: Building2 },
    { id: "navigation" as Tab, label: "Nav", icon: Map },
    { id: "agents" as Tab, label: "Agents", icon: Bot },
    { id: "ai" as Tab, label: "AI", icon: Sparkles },
    { id: "office" as Tab, label: "Office", icon: Building2 },
    { id: "monitoring" as Tab, label: "Monitor", icon: BarChart3 },
    { id: "versions" as Tab, label: "Versions", icon: GitBranch },
  ];

  // Sections for the visual sidebar — only show relevant tabs
  const sidebarSections = [
    {
      label: "Create",
      items: [
        { id: "chat" as Tab, label: "Chat", icon: MessageSquare, shortcut: "⌘1" },
        { id: "preview" as Tab, label: "Preview", icon: Eye, shortcut: "⌘2" },
        { id: "code" as Tab, label: "Code", icon: Code, shortcut: "⌘3" },
      ],
    },
    {
      label: "Model",
      items: [
        { id: "data" as Tab, label: "Data Model", icon: Database },
        { id: "rules" as Tab, label: "Rules", icon: Shield },
        { id: "business-rules" as Tab, label: "Business Rules", icon: Scale },
        { id: "workflows" as Tab, label: "Workflows", icon: Workflow },
        { id: "agents" as Tab, label: "Agents", icon: Bot },
      ],
    },
    {
      label: "Design",
      items: [
        { id: "editor" as Tab, label: "Editor", icon: Layout },
        { id: "navigation" as Tab, label: "Pages & Nav", icon: Map },
      ],
    },
  ];

  // Fetch app model for command palette context
  const { data: appModel } = useQuery({
    queryKey: ["project", projectId, "app-model"],
    queryFn: () =>
      api.get<{
        database?: { tables?: { name: string }[] };
        pages?: { path: string; component: string }[];
        components?: { name: string }[];
      }>(`/api/projects/${projectId}/app-model`),
    enabled: !!project,
  });

  // Command palette items
  const commandItems: CommandItem[] = useMemo(() => {
    const items: CommandItem[] = [
      // Navigation commands for all tabs
      ...tabs.map((t) => ({
        id: `nav-${t.id}`,
        label: `Go to ${t.label}`,
        category: "navigation" as const,
        shortcut:
          t.id === "chat"
            ? "\u2318 1"
            : t.id === "preview"
              ? "\u2318 2"
              : t.id === "code"
                ? "\u2318 3"
                : undefined,
        action: () => setActiveTab(t.id),
      })),

      // Action commands
      {
        id: "action-export",
        label: "Export Project",
        description: "Download ZIP or generate Dockerfile",
        category: "action" as const,
        action: () => setShowExport(true),
      },
      {
        id: "action-delete",
        label: "Delete Project",
        description: "Permanently remove this project",
        category: "action" as const,
        action: () => setShowDelete(true),
      },
      {
        id: "action-back",
        label: "Back to Projects",
        description: "Return to project list",
        category: "navigation" as const,
        action: () => router.push(`/org/${orgId}/projects`),
      },
      {
        id: "action-new-rule",
        label: "Create Rule",
        description: "Add a new business or validation rule",
        category: "rule" as const,
        action: () => setActiveTab("rules"),
      },
      {
        id: "action-new-workflow",
        label: "Create Workflow",
        description: "Design a new workflow",
        category: "workflow" as const,
        action: () => setActiveTab("workflows"),
      },
    ];

    // App-model-aware commands: data models
    if (appModel?.database?.tables) {
      for (const table of appModel.database.tables) {
        items.push({
          id: `model-${table.name}`,
          label: `View model: ${table.name}`,
          description: "Open in data model editor",
          category: "model" as const,
          action: () => setActiveTab("data"),
        });
      }
    }

    // App-model-aware commands: pages
    if (Array.isArray(appModel?.pages)) {
      for (const page of appModel.pages) {
        items.push({
          id: `page-${page.path}`,
          label: `Page: ${page.component}`,
          description: page.path,
          category: "page" as const,
          action: () => setActiveTab("navigation"),
        });
      }
    }

    // App-model-aware commands: components
    if (Array.isArray(appModel?.components)) {
      for (const comp of appModel.components) {
        items.push({
          id: `component-${comp.name}`,
          label: `Component: ${comp.name}`,
          description: "View in code editor",
          category: "component" as const,
          action: () => setActiveTab("code"),
        });
      }
    }

    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appModel, orgId]);

  const onGenerationComplete = () => {
    // Invalidate ALL editor queries so they refetch after AI generation
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    queryClient.invalidateQueries({ queryKey: ["project", projectId, "conversations"] });
    queryClient.invalidateQueries({ queryKey: ["project", projectId, "versions"] });
    queryClient.invalidateQueries({ queryKey: ["project", projectId, "workflows"] });
    queryClient.invalidateQueries({ queryKey: ["project", projectId, "rules"] });
    queryClient.invalidateQueries({ queryKey: ["project", projectId, "business-rules"] });
    queryClient.invalidateQueries({ queryKey: ["project", projectId, "navigation"] });
    queryClient.invalidateQueries({ queryKey: ["project", projectId, "modules-layout"] });
    queryClient.invalidateQueries({ queryKey: ["project", projectId, "app-model"] });
    // The define run just wrote it — without this the gate would show the
    // Blueprint as it stood before the run that produced it.
    queryClient.invalidateQueries({ queryKey: ["project", projectId, "blueprint"] });
  };

  return (
    <div className="flex h-full">
      {/* Project header bar */}
      <div className="absolute top-0 left-[220px] right-0 z-10 flex h-[70px] items-center justify-between border-b border-slate-200/80 bg-white/80 backdrop-blur-sm px-4 dark:bg-slate-900/80 dark:border-slate-800">
        <div className="flex items-center gap-3">
          <button
            onClick={() => window.history.back()}
            className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors dark:hover:bg-slate-800"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="text-sm font-medium text-slate-900 dark:text-white truncate max-w-[200px]">
            {project?.name || "..."}
          </span>
          {project?.description && (
            <span className="hidden md:inline text-xs text-slate-400 truncate max-w-[300px]">
              {project.description.length > 60 ? project.description.slice(0, 60) + "..." : project.description}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <Tooltip label="Agents" shortcut="">
            <button
              onClick={() => setActiveTab("office")}
              aria-label="Agents"
              className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${activeTab === "office" ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900" : "text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"}`}
            >
              <Building2 className="h-3.5 w-3.5" />
            </button>
          </Tooltip>
          <Tooltip label="History">
            <button
              onClick={() => setActiveTab("versions")}
              aria-label="History"
              className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${activeTab === "versions" ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900" : "text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"}`}
            >
              <GitBranch className="h-3.5 w-3.5" />
            </button>
          </Tooltip>
          <div className="w-px h-4 bg-slate-200 mx-1 dark:bg-slate-700" />
          <Tooltip label={syncIntegrations.isPending ? "Syncing…" : "Sync integrations to .env"}>
            <button
              onClick={() => syncIntegrations.mutate()}
              disabled={syncIntegrations.isPending}
              className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors dark:hover:bg-slate-800 disabled:opacity-50 disabled:cursor-wait"
            >
              <KeyRound className={`h-3.5 w-3.5 ${syncIntegrations.isPending ? "animate-pulse" : ""}`} />
            </button>
          </Tooltip>
          <Tooltip label="Export">
            <button
              onClick={() => setShowExport(true)}
              className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors dark:hover:bg-slate-800"
            >
              <Download className="h-3.5 w-3.5" />
            </button>
          </Tooltip>
          <div className="w-px h-4 bg-slate-200 mx-1 dark:bg-slate-700" />
          <PublishButton projectId={projectId} orgId={orgId} />
        </div>
      </div>

      {/* Tab sidebar — 9 tabs in 3 sections with tooltips */}
      <div className="flex w-12 flex-col items-center border-r border-slate-200/80 bg-white pt-[70px] pb-3 shrink-0 dark:bg-slate-900 dark:border-slate-800">
        {sidebarSections.map((section, si) => (
          <div key={section.label} className="w-full">
            {si > 0 && (
              <div className="mx-2.5 my-2 border-t border-slate-100 dark:border-slate-800" />
            )}
            <div className="flex flex-col items-center gap-0.5 px-1.5">
              {section.items.map(({ id, label, icon: Icon, ...rest }) => (
                <Tooltip key={id} label={label} shortcut={"shortcut" in rest ? (rest as { shortcut?: string }).shortcut : undefined}>
                  <button
                    onClick={() => setActiveTab(id)}
                    /* A3-1: Tooltip gives a VISUAL label but no accessible name,
                       so the workspace's primary navigation announced as a bare
                       "button" (WCAG 2.2 4.1.2). Every tab already carries
                       `label` — it simply was not exposed. */
                    aria-label={label}
                    aria-current={activeTab === id ? "page" : undefined}
                    className={`relative flex h-9 w-9 items-center justify-center rounded-lg transition-all duration-150 ${
                      activeTab === id
                        ? "bg-slate-900 text-white shadow-sm dark:bg-white dark:text-slate-900"
                        : "text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                    }`}
                  >
                    <Icon className="h-[16px] w-[16px]" />
                  </button>
                </Tooltip>
              ))}
            </div>
          </div>
        ))}

        <div className="flex-1" />

        <Tooltip label="Delete project">
          <button
            onClick={() => setShowDelete(true)}
              aria-label="Delete project"
            className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-300 hover:bg-red-50 hover:text-red-500 transition-colors dark:text-slate-600 dark:hover:bg-red-950/30"
          >
            <Trash2 className="h-[16px] w-[16px]" />
          </button>
        </Tooltip>
      </div>

      {/* Main content area */}
      <div className="flex-1 overflow-hidden pt-[70px] bg-background">
        {/*
          HIDDEN, NOT UNMOUNTED. Every other tab here is safe to tear down and
          rebuild from its query cache; the chat is not. Its transcript and its
          run live in component state, so `activeTab === "chat" && <SmithPanel/>`
          threw the conversation away on the way to Preview and brought back a
          blank pane — and a build streaming over SSE lost its reader mid-run,
          the one moment someone is most likely to go and look at the preview.

          This keeps the tab switch cheap without making the panel own a cache
          it has no way to fill: what survives a *navigation* away from the
          project is a separate question, and needs the turns persisted
          server-side rather than a different render here.
        */}
        <div className={activeTab === "chat" ? "h-full" : "hidden"}>
          <SmithPanel
            projectId={projectId}
            blueprint={blueprintDoc ?? null}
            onRunComplete={onGenerationComplete}
            className="h-full border-l-0"
          />
        </div>
        {activeTab === "preview" && (
          <PreviewFrame projectId={projectId} project={project || null} />
        )}
        {activeTab === "code" && <CodePanel projectId={projectId} />}
        {activeTab === "data" && (
          <DataModelPanel
            projectId={projectId}
            dbPort={project?.db_port}
          />
        )}
        {activeTab === "rules" && (
          <RulesPanel projectId={projectId} orgId={orgId} />
        )}
        {activeTab === "business-rules" && (
          <BusinessRulesPanel projectId={projectId} orgId={orgId} />
        )}
        {activeTab === "decisions" && (
          <DRDEditorPanel projectId={projectId} />
        )}
        {activeTab === "workflows" && (
          <WorkflowPanel projectId={projectId} orgId={orgId} />
        )}
        {activeTab === "editor" && project?.short_id && (
          <VisualEditorWorkspace projectId={project.short_id} />
        )}
        {/* Legacy individual editors — accessible via command palette */}
        {activeTab === "design" && (
          <VisualEditor
            projectId={projectId}
            initialRoute={activeDesignRoute}
            onEditStructure={() => setActiveTab("design-editor")}
          />
        )}
        {activeTab === "design-editor" && (
          <DesignEditor
            projectId={projectId}
            onCompiled={(route) => {
              setActiveDesignRoute(route);
              setActiveTab("design");
            }}
          />
        )}
        {activeTab === "ir-editor" && (
          <IREditor projectId={projectId} />
        )}
        {activeTab === "navigation" && (
          <NavigationPanel projectId={projectId} />
        )}
        {activeTab === "agents" && (
          <AgentBuilderPanel projectId={projectId} orgId={orgId} />
        )}
        {activeTab === "ai" && (
          <AIFeaturesPanel projectId={projectId} />
        )}
        {activeTab === "office" && (
          <VirtualOffice
            className="h-full"
            isGenerating={useChatStore.getState().isGenerating}
          />
        )}
        {activeTab === "monitoring" && (
          <CostTrackingPanel projectId={projectId} />
        )}
        {activeTab === "versions" && (
          <HistoryPanel projectId={projectId} />
        )}
      </div>

      <ExportDialog
        open={showExport}
        onOpenChange={setShowExport}
        projectId={projectId}
        projectName={project?.name || "app"}
      />

      <DeleteProjectDialog
        open={showDelete}
        onOpenChange={setShowDelete}
        projectId={projectId}
        projectName={project?.name || "Project"}
        onDeleted={() => {
          queryClient.invalidateQueries({
            queryKey: ["org", orgId, "projects"],
          });
          router.push(`/org/${orgId}/projects`);
        }}
      />

      <CommandPalette
        open={showCommandPalette}
        onOpenChange={setShowCommandPalette}
        items={commandItems}
      />
    </div>
  );
}

export default function ProjectPage({
  params,
}: {
  params: Promise<{ orgId: string; projectId: string }>;
}) {
  const { orgId, projectId } = use(params);
  return <ProjectWorkspace orgId={orgId} projectId={projectId} />;
}
