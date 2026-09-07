"use client";
import * as React from "react";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronRight, Home, Eye, Plus, List as ListIcon, FileText,
  PanelLeftClose, Layout, FilePlus,
} from "lucide-react";
import { useEditorStore, flushPersister } from "@/lib/editor-store";
import { NewPageDialog } from "@/components/editor/NewPageDialog";
import type { ScaffoldedPage } from "@/lib/page-scaffold";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface PagePickerProps {
  projectId: string;
  value: string;
  onChange: (slug: string) => void;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
}

interface NavFlowPage {
  id: string;
  route: string;
  title: string;
}

/**
 * Internal page-type used to pick an icon. Always returns a label so the
 * icon resolver gets a stable key.
 */
function pageTypeLabel(route: string): string {
  if (!route) return "";
  if (route === "/" || route === "/home") return "HOME";
  if (route.endsWith("/new") || route.endsWith("/create")) return "FORM";
  if (route.endsWith("/edit")) return "FORM";
  if (route.includes("[id]")) return "DETAIL";
  const segs = route.split("/").filter(Boolean);
  if (segs.length === 1) return segs[0].toUpperCase();
  return (segs[segs.length - 1] ?? "").toUpperCase();
}

/**
 * The tag shown in the UI — only when it ADDS information beyond what the
 * route + icon already convey. Tags that just repeat the route segment
 * (LOGIN / SIGNUP / TASKS / etc.) are redundant noise and we omit them.
 */
function pageTagToDisplay(route: string): string {
  const t = pageTypeLabel(route);
  // Always show structural tags
  if (t === "HOME" || t === "FORM" || t === "DETAIL") return t;
  // For everything else, the route segment is the tag — drop it
  return "";
}

function pageIcon(route: string) {
  const t = pageTypeLabel(route);
  if (t === "HOME") return Home;
  if (t === "FORM") return Plus;
  if (t === "DETAIL") return Eye;
  if (t === "LIST") return ListIcon;
  return FileText;
}

const SECTION_HDR =
  "px-3 py-1.5 flex items-center justify-between text-[10px] font-semibold tracking-wide text-muted-foreground uppercase";

export function PagePicker({
  projectId, value, onChange,
  collapsed = false, onToggleCollapsed,
}: PagePickerProps) {
  const artifacts = useEditorStore((s) => s.artifacts);
  const selectedNodeId = useEditorStore((s) => s.selectedNodeId);
  const setSelection = useEditorStore((s) => s.setSelection);
  const dispatch = useEditorStore((s) => s.dispatch);
  const queryClient = useQueryClient();
  const [newPageOpen, setNewPageOpen] = useState(false);

  const { data: navFlow } = useQuery({
    queryKey: ["nav-flow", projectId],
    queryFn: async () => {
      const r = await fetch(
        `${API}/api/_debug/project-file/${projectId}/src/contracts/nav-flow.json`
      );
      return r.ok ? r.json() : { pages: [] };
    },
    enabled: !!projectId,
  });

  const pages: NavFlowPage[] = (navFlow as any)?.pages ?? [];

  // What "New page" must de-duplicate against is the EDIT STORE, not this
  // query: `dispatch({type:"addPage"})` lands in `artifacts`, and the query
  // returns `{ pages: [] }` on any non-ok response and is undefined while
  // loading. De-duplicating against the query alone meant that opening the
  // dialog before the fetch settled (or with the backend down) offered a slug
  // that collided with a real page. applyAction now refuses the collision, so
  // the worst case is a clear error instead of a destroyed page — but taking
  // the union here means the dialog disambiguates the slug up front and the
  // user never sees the error at all.
  const takenPageIds = React.useMemo(() => {
    const ids = new Set<string>(pages.map((p) => p.id));
    for (const id of Object.keys((artifacts as any)?.pageSchemas ?? {})) ids.add(id);
    for (const p of ((artifacts as any)?.navFlow?.pages ?? []) as NavFlowPage[]) {
      if (p?.id) ids.add(p.id);
    }
    return [...ids];
  }, [pages, artifacts]);
  const takenRoutes = React.useMemo(() => {
    const routes = new Set<string>(pages.map((p) => p.route).filter(Boolean));
    for (const p of ((artifacts as any)?.navFlow?.pages ?? []) as NavFlowPage[]) {
      if (p?.route) routes.add(p.route);
    }
    return [...routes];
  }, [pages, artifacts]);

  // Create a scaffolded page: add it to the store, flush to disk so the picker
  // + canvas can load it, refresh the nav-flow query, then activate it.
  const handleCreatePage = async (page: ScaffoldedPage) => {
    dispatch({
      type: "addPage",
      pageId: page.pageId,
      route: page.route,
      title: page.title,
      root: page.root as any,
    });
    if (useEditorStore.getState().lastError) return; // rejected — leave it surfaced
    try {
      await flushPersister();
    } catch {
      /* best-effort — the store already has the page */
    }
    await queryClient.invalidateQueries({ queryKey: ["nav-flow", projectId] });
    onChange(page.pageId);
  };

  // Does the project have a shell.json? When yes, surface it as a dedicated
  // top-level entry in the picker so the user can edit the app shell as a
  // first-class artifact (its own header, nav, sidebar, footer).
  const { data: shellExists } = useQuery({
    queryKey: ["shell-exists", projectId],
    queryFn: async () => {
      const r = await fetch(
        `${API}/api/_debug/project-file/${projectId}/src/schemas/shell.json`
      );
      return r.ok;
    },
    enabled: !!projectId,
    staleTime: 60_000,
  });

  // Walk the current page's tree from artifacts (if loaded)
  const currentPageNodes = (() => {
    const page = (artifacts?.pageSchemas as any)?.[value];
    if (!page?.root) return null;
    return page.root;
  })();

  if (collapsed) {
    return (
      <aside className="w-10 border-r bg-background flex flex-col h-full">
        <button
          onClick={onToggleCollapsed}
          className="h-10 w-10 grid place-items-center hover:bg-muted text-muted-foreground hover:text-foreground border-b"
          title="Expand Pages"
          aria-label="Expand pages panel"
        >
          <ChevronRight size={16} />
        </button>
        <button
          onClick={onToggleCollapsed}
          className="flex-1 hover:bg-muted text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
          title="Expand pages panel"
          style={{ writingMode: "vertical-rl" }}
        >
          Pages
        </button>
      </aside>
    );
  }

  return (
    <nav className="w-60 border-r bg-background flex flex-col h-full">
      <header className={SECTION_HDR}>
        <span>Pages</span>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setNewPageOpen(true)}
            className="text-muted-foreground hover:text-foreground"
            title="New page"
            aria-label="New page"
          >
            <FilePlus size={14} />
          </button>
          {onToggleCollapsed && (
            <button
              onClick={onToggleCollapsed}
              className="text-muted-foreground hover:text-foreground"
              title="Collapse pages panel"
              aria-label="Collapse pages panel"
            >
              <PanelLeftClose size={14} />
            </button>
          )}
        </div>
      </header>

      <NewPageDialog
        open={newPageOpen}
        onOpenChange={setNewPageOpen}
        existingPageIds={takenPageIds}
        existingRoutes={takenRoutes}
        onCreate={handleCreatePage}
      />

      <button
        onClick={() => setNewPageOpen(true)}
        className="mx-3 my-2 flex items-center justify-center gap-1.5 rounded-md border border-dashed py-1.5 text-xs text-muted-foreground hover:border-foreground/40 hover:text-foreground"
      >
        <Plus size={13} /> New page
      </button>

      <div className="overflow-y-auto">
        {/* App shell — the persistent layout (header / nav / sidebar / footer)
            that wraps every authenticated page. Lives in src/schemas/shell.json
            and is editable just like any other schema. */}
        {shellExists && (
          <>
            <button
              onClick={() => onChange("shell")}
              className={`group w-full text-left px-3 py-1.5 flex items-center gap-2 text-sm ${
                value === "shell" ? "bg-muted/60" : "hover:bg-muted/40"
              }`}
              title="Edit the app shell — header / nav / sidebar / footer"
            >
              <Layout
                size={14}
                className={value === "shell" ? "text-foreground" : "text-muted-foreground"}
              />
              <span className={`flex-1 truncate text-[12px] ${value === "shell" ? "font-medium" : ""}`}>
                App Shell
              </span>
              <span className="text-[10px] tracking-wide text-muted-foreground">LAYOUT</span>
            </button>
            <div className="h-px bg-border my-1 mx-2" />
          </>
        )}

        {pages.length === 0 && (
          <p className="px-3 py-2 text-xs text-muted-foreground">No nav-flow.</p>
        )}
        {pages.map((p) => {
          const Icon = pageIcon(p.route);
          const isActive = p.id === value;
          const tag = pageTagToDisplay(p.route);
          return (
            <button
              key={p.id}
              onClick={() => onChange(p.id)}
              className={`group w-full text-left px-3 py-1.5 flex items-center gap-2 text-sm ${
                isActive ? "bg-muted/60" : "hover:bg-muted/40"
              }`}
            >
              <Icon
                size={14}
                className={isActive ? "text-foreground" : "text-muted-foreground"}
              />
              <span className={`flex-1 truncate font-mono text-[12px] ${isActive ? "font-medium" : ""}`}>
                {p.route}
              </span>
              {tag && (
                <span className="text-[10px] tracking-wide text-muted-foreground">{tag}</span>
              )}
            </button>
          );
        })}

        {currentPageNodes && (
          <>
            <div className="h-px bg-border my-2 mx-2" />
            <NodeTree
              node={currentPageNodes}
              depth={0}
              selectedNodeId={selectedNodeId}
              onSelect={setSelection}
            />
          </>
        )}
      </div>
    </nav>
  );
}

interface TreeNode {
  id: string;
  type: string;
  children?: TreeNode[];
}

interface NodeTreeProps {
  node: TreeNode;
  depth: number;
  selectedNodeId: string | null;
  onSelect: (id: string | null) => void;
}

function NodeTree({ node, depth, selectedNodeId, onSelect }: NodeTreeProps) {
  const isActive = node.id === selectedNodeId;
  return (
    <>
      <button
        onClick={() => onSelect(node.id)}
        className={`w-full text-left px-3 py-1 flex items-center gap-1.5 text-xs ${
          isActive
            ? "bg-blue-500/15 text-blue-700 dark:text-blue-300"
            : "hover:bg-muted/40 text-foreground/80"
        }`}
        style={{ paddingLeft: 12 + depth * 12 }}
      >
        <span className="truncate">{node.type}</span>
      </button>
      {(node.children ?? []).map((child, i) => (
        <NodeTree
          key={child.id ?? i}
          node={child}
          depth={depth + 1}
          selectedNodeId={selectedNodeId}
          onSelect={onSelect}
        />
      ))}
    </>
  );
}
