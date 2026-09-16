"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronRight, Home, Eye, Plus, List as ListIcon, FileText,
  PanelLeftClose, Layout, FilePlus, Trash2,
} from "lucide-react";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
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
  // Which page the app opens on — the delete confirmation says so when it is
  // about to move, because that is the one consequence a user cannot see.
  const initialPageId: string | undefined = (navFlow as any)?.initialPage;

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

  /**
   * ED-14 — delete a page.
   *
   * `removePage` has been in the reducer all along, atomic across pageSchemas +
   * navFlow + transitions and with a working undo, and nothing ever dispatched
   * it: the editor could add a page but not remove one. This is the missing
   * caller, and it mirrors handleCreatePage above step for step so the two
   * halves persist the same way.
   */
  const [pendingDelete, setPendingDelete] = useState<NavFlowPage | null>(null);

  const handleDeletePage = async (page: NavFlowPage) => {
    setPendingDelete(null);
    // Worked out BEFORE the dispatch: after it, the store no longer knows this
    // page existed, and we still need somewhere to send the user.
    const fallback = pages.find((p) => p.id !== page.id)?.id;

    dispatch({ type: "removePage", pageId: page.id });
    if (useEditorStore.getState().lastError) return; // rejected — leave it surfaced

    try {
      await flushPersister();
    } catch {
      /* best-effort — the store no longer has the page either way */
    }
    await queryClient.invalidateQueries({ queryKey: ["nav-flow", projectId] });
    // Deleting the page you were looking at would otherwise leave the canvas
    // pointed at a page that no longer exists.
    if (page.id === value && fallback) onChange(fallback);
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

      {/* Deleting a page is not just removing a row: removePage also drops every
          transition that pointed at it, and hands the entry point to another
          page if this one held it. That is worth one question first. */}
      <Dialog open={!!pendingDelete} onOpenChange={(o) => { if (!o) setPendingDelete(null); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Delete this page?</DialogTitle>
            <DialogDescription>
              <span className="font-mono text-foreground">{pendingDelete?.route}</span>
              {pendingDelete?.title ? ` — ${pendingDelete.title}` : ""}
              <br />
              Its navigation links are removed with it
              {pendingDelete && initialPageId === pendingDelete.id
                ? ", and the app's entry page moves to the next page in the list"
                : ""}
              . You can undo this.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingDelete(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              data-confirm-delete-page=""
              onClick={() => { if (pendingDelete) void handleDeletePage(pendingDelete); }}
            >
              Delete page
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <NewPageDialog
        open={newPageOpen}
        onOpenChange={setNewPageOpen}
        existingPageIds={pages.map((p) => p.id)}
        existingRoutes={pages.map((p) => p.route)}
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
          // The row was a single <button>; a delete control cannot nest inside
          // one (invalid HTML, and the click would fight the row's own handler).
          // The row is now a flex container holding two real buttons.
          return (
            <div
              key={p.id}
              className={`group w-full flex items-center text-sm ${
                isActive ? "bg-muted/60" : "hover:bg-muted/40"
              }`}
            >
              <button
                onClick={() => onChange(p.id)}
                className="min-w-0 flex-1 text-left px-3 py-1.5 flex items-center gap-2"
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
              {/* The last page is not deletable: a project with no pages has
                  nothing to render and no route to fall back to. */}
              {pages.length > 1 && (
                <button
                  type="button"
                  onClick={() => setPendingDelete(p)}
                  title={`Delete ${p.route}`}
                  aria-label={`Delete page ${p.route}`}
                  data-delete-page={p.id}
                  className="shrink-0 px-2 py-1.5 text-muted-foreground opacity-0 transition-opacity hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
                >
                  <Trash2 size={13} />
                </button>
              )}
            </div>
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
