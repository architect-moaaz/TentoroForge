"use client";

/**
 * Page Flow Panel — mini React Flow canvas showing page navigation.
 *
 * Displays pages as nodes, navigation links as edges.
 * Auto-detects links from data-action="navigate" in page HTML.
 */

import { useMemo, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type OnNodesChange,
  useNodesState,
  useEdgesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  FileText, ArrowRight, FormInput, List, Eye, LayoutDashboard,
  LogIn, AlertTriangle, Settings, File,
} from "lucide-react";

interface PageFlowPanelProps {
  projectId: string;
  pages: Array<{
    pageId: string;
    route: string;
    title?: string;
    html: string;
  }>;
  activePageId: string | null;
  onSelectPage: (pageId: string) => void;
}

type PageType = "form" | "list" | "detail" | "dashboard" | "auth" | "error" | "settings" | "page";

const PAGE_TYPE_META: Record<PageType, { icon: typeof FileText; color: string; label: string }> = {
  form:      { icon: FormInput,       color: "text-violet-600 bg-violet-50",   label: "Form" },
  list:      { icon: List,            color: "text-blue-600 bg-blue-50",       label: "List" },
  detail:    { icon: Eye,             color: "text-amber-600 bg-amber-50",     label: "Detail" },
  dashboard: { icon: LayoutDashboard, color: "text-emerald-600 bg-emerald-50", label: "Dashboard" },
  auth:      { icon: LogIn,           color: "text-rose-600 bg-rose-50",       label: "Auth" },
  error:     { icon: AlertTriangle,   color: "text-red-600 bg-red-50",         label: "Error" },
  settings:  { icon: Settings,        color: "text-slate-600 bg-slate-50",     label: "Settings" },
  page:      { icon: File,            color: "text-gray-600 bg-gray-50",       label: "Page" },
};

function classifyPage(page: { pageId: string; route: string; html: string }): PageType {
  const r = page.route.toLowerCase();
  const id = page.pageId.toLowerCase();

  // Auth pages
  if (/\/(login|signin|signup|register|forgot-password|reset-password)$/.test(r)) return "auth";

  // Error pages
  if (/\/(error|not-found|404|500)$/.test(r) || id.includes("error") || id.includes("not-found")) return "error";

  // Dashboard
  if (/^\/(dashboard)?$/.test(r) || id === "dashboard" || id === "home") return "dashboard";

  // Settings
  if (/\/settings/.test(r) || /\/profile$/.test(r)) return "settings";

  // Forms: /new, /create, /edit — or HTML contains <form
  if (/\/(new|create|edit)$/.test(r) || page.html.includes("<form")) return "form";

  // Detail: /[id], /[slug], etc.
  if (/\/\[\w+\]$/.test(r)) return "detail";

  // List: entity root routes (e.g. /users, /projects) — has no dynamic segment at end
  const segments = r.split("/").filter(Boolean);
  if (segments.length >= 1 && !segments[segments.length - 1].startsWith("[")) return "list";

  return "page";
}

export function PageFlowPanel({
  projectId,
  pages,
  activePageId,
  onSelectPage,
}: PageFlowPanelProps) {
  // Classify pages
  const classifiedPages = useMemo(
    () => pages.map((p) => ({ ...p, type: classifyPage(p) })),
    [pages],
  );

  // Group pages by type for the list view
  const groupedPages = useMemo(() => {
    const groups = new Map<PageType, typeof classifiedPages>();
    const order: PageType[] = ["dashboard", "list", "detail", "form", "auth", "settings", "error", "page"];
    for (const p of classifiedPages) {
      const arr = groups.get(p.type) || [];
      arr.push(p);
      groups.set(p.type, arr);
    }
    return order.filter((t) => groups.has(t)).map((t) => ({ type: t, pages: groups.get(t)! }));
  }, [classifiedPages]);

  // Build nodes from pages
  const initialNodes: Node[] = useMemo(() => {
    return classifiedPages.map((page, i) => {
      const meta = PAGE_TYPE_META[page.type];
      const Icon = meta.icon;
      return {
        id: page.pageId,
        type: "default",
        position: { x: 50, y: i * 100 + 20 },
        data: {
          label: (
            <div
              className="flex items-center gap-1.5 cursor-pointer"
              onClick={() => onSelectPage(page.pageId)}
            >
              <Icon className="h-3 w-3 shrink-0" />
              <div className="min-w-0">
                <div className="text-xs font-medium truncate">
                  {page.title || page.pageId}
                </div>
                <div className="text-[10px] text-gray-500 truncate">
                  {page.route}
                </div>
              </div>
            </div>
          ),
        },
        style: {
          border: page.pageId === activePageId ? "2px solid #841013" : "1px solid #e5e7eb",
          borderRadius: "8px",
          padding: "4px 8px",
          background: page.pageId === activePageId ? "#fff5f5" : "white",
          fontSize: "11px",
          width: 160,
        },
      };
    });
  }, [classifiedPages, activePageId, onSelectPage]);

  // Extract navigation edges from HTML content
  const initialEdges: Edge[] = useMemo(() => {
    const edges: Edge[] = [];
    const routeToPage = new Map(pages.map((p) => [p.route, p.pageId]));

    for (const page of pages) {
      // Find all data-action="navigate" data-action-to="/route" in HTML
      const navMatches = page.html.matchAll(/data-action="navigate"[^>]*data-action-to="([^"]+)"/g);
      for (const match of navMatches) {
        const targetRoute = match[1];
        const targetPageId = routeToPage.get(targetRoute);
        if (targetPageId && targetPageId !== page.pageId) {
          const edgeId = `${page.pageId}->${targetPageId}`;
          if (!edges.find((e) => e.id === edgeId)) {
            edges.push({
              id: edgeId,
              source: page.pageId,
              target: targetPageId,
              animated: true,
              style: { stroke: "#841013" },
              label: targetRoute,
              labelStyle: { fontSize: 9 },
            });
          }
        }
      }

      // Also check data-action-to without data-action prefix
      const hrefMatches = page.html.matchAll(/data-action-to="([^"]+)"/g);
      for (const match of hrefMatches) {
        const targetRoute = match[1];
        const targetPageId = routeToPage.get(targetRoute);
        if (targetPageId && targetPageId !== page.pageId) {
          const edgeId = `${page.pageId}->${targetPageId}`;
          if (!edges.find((e) => e.id === edgeId)) {
            edges.push({
              id: edgeId,
              source: page.pageId,
              target: targetPageId,
              style: { stroke: "#94a3b8" },
            });
          }
        }
      }
    }

    return edges;
  }, [pages]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  if (pages.length === 0) {
    return (
      <div className="p-4 text-center">
        <FileText className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
        <p className="text-sm text-muted-foreground">No pages yet</p>
      </div>
    );
  }

  return (
    <div className="h-[300px] border-b">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        proOptions={{ hideAttribution: true }}
        minZoom={0.5}
        maxZoom={1.5}
      >
        <Background gap={12} size={1} color="#f1f5f9" />
        <Controls showInteractive={false} />
      </ReactFlow>

      {/* Page list below the flow — grouped by type */}
      <div className="p-3 space-y-3 overflow-y-auto max-h-[300px]">
        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Pages ({pages.length})
        </h4>
        {groupedPages.map(({ type, pages: groupPages }) => {
          const meta = PAGE_TYPE_META[type];
          const GroupIcon = meta.icon;
          return (
            <div key={type}>
              <div className="flex items-center gap-1.5 mb-1">
                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${meta.color}`}>
                  <GroupIcon className="h-2.5 w-2.5" />
                  {meta.label}
                </span>
                <span className="text-[10px] text-muted-foreground">{groupPages.length}</span>
              </div>
              <div className="space-y-0.5">
                {groupPages.map((page) => {
                  const Icon = meta.icon;
                  return (
                    <button
                      key={page.pageId}
                      onClick={() => onSelectPage(page.pageId)}
                      className={`w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-muted transition-colors ${
                        page.pageId === activePageId ? "bg-muted font-medium" : ""
                      }`}
                    >
                      <Icon className={`h-3.5 w-3.5 shrink-0 ${meta.color.split(" ")[0]}`} />
                      <div className="min-w-0 flex-1">
                        <div className="truncate">{page.title || page.pageId}</div>
                        <div className="text-[10px] text-muted-foreground truncate">
                          {page.route}
                        </div>
                      </div>
                      {page.pageId === activePageId && (
                        <ArrowRight className="h-3 w-3 text-primary shrink-0" />
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
