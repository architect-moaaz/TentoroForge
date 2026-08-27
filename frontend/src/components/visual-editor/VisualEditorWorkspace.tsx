"use client";
/**
 * The full visual editor workspace — toolbar + tabs + palette + canvas + props.
 * Used by both the standalone /editor/<id> route and the project workspace's
 * "Editor" tab so the two share a single source of truth.
 */
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Palette } from "@/components/palette/Palette";
import { PagePicker } from "@/components/editor/PagePicker";
import { Canvas } from "@/components/canvas/Canvas";
import { ZoomControls } from "@/components/canvas/ZoomControls";
import { RightPanel } from "@/components/properties/RightPanel";
import { EditorToolbar } from "@/components/editor/EditorToolbar";
import { PageTabs } from "@/components/editor/PageTabs";
import { ErrorBanner } from "@/components/editor/ErrorBanner";
import { useKeymap } from "@/lib/keymap";
import { useEditorBreakpoint } from "@/hooks/useMediaQuery";
import { useEditorStore, flushPersister, attachPersister } from "@/lib/editor-store";

type Device = "mobile" | "tablet" | "desktop";
type PanelKey = "palette" | "pages" | "properties";

export interface VisualEditorWorkspaceProps {
  projectId: string;
  /** Hide the EditorToolbar when the outer chrome already provides one. */
  hideToolbar?: boolean;
  /** Hide the PageTabs strip below the toolbar. */
  hidePageTabs?: boolean;
}

export function VisualEditorWorkspace({
  projectId,
  hideToolbar = false,
  hidePageTabs = false,
}: VisualEditorWorkspaceProps) {
  const [pageSlug, setPageSlug] = useState<string>("home");
  const [openPages, setOpenPages] = useState<string[]>(["home"]);
  const [device, setDevice] = useState<Device>("desktop");
  const [openPanel, setOpenPanel] = useState<PanelKey | null>(null);
  const [pagesCollapsed, setPagesCollapsed] = useState<boolean>(false);
  const [paletteCollapsed, setPaletteCollapsed] = useState<boolean>(false);
  const [rightCollapsed, setRightCollapsed] = useState<boolean>(false);
  const [zoom, setZoom] = useState<number>(1);
  const { isDesktop } = useEditorBreakpoint();
  const isDirty = useEditorStore((s) => s.isDirty);
  const markClean = useEditorStore((s) => s.markClean);
  const setSaveError = useEditorStore((s) => s.setSaveError);
  useKeymap();

  // Persist view-only UI prefs (device / zoom / rail collapse) per project so
  // the user's tailored workspace survives a reload. Kept out of the
  // schema/persistence layer — this is view state, not app data.
  const uiPrefsKey = `editor:ui:${projectId}`;
  useEffect(() => {
    try {
      const raw = localStorage.getItem(uiPrefsKey);
      if (!raw) return;
      const p = JSON.parse(raw);
      if (p.device === "mobile" || p.device === "tablet" || p.device === "desktop") setDevice(p.device);
      if (typeof p.zoom === "number") setZoom(p.zoom);
      if (typeof p.pagesCollapsed === "boolean") setPagesCollapsed(p.pagesCollapsed);
      if (typeof p.paletteCollapsed === "boolean") setPaletteCollapsed(p.paletteCollapsed);
      if (typeof p.rightCollapsed === "boolean") setRightCollapsed(p.rightCollapsed);
    } catch { /* ignore corrupt prefs */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uiPrefsKey]);
  useEffect(() => {
    try {
      localStorage.setItem(uiPrefsKey, JSON.stringify({ device, zoom, pagesCollapsed, paletteCollapsed, rightCollapsed }));
    } catch { /* ignore quota / private mode */ }
  }, [uiPrefsKey, device, zoom, pagesCollapsed, paletteCollapsed, rightCollapsed]);

  // Default the active page from nav-flow once it loads. The initial "home"
  // slug is a placeholder — most generated apps have no page with id "home",
  // so the canvas would show "No schema at home.json" until the user clicks a
  // page. Shares PagePicker's ["nav-flow", projectId] query key, so this is
  // served from cache (no extra request). We only redirect while the user is
  // still on the untouched "home" placeholder — never stomp a real selection.
  const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
  const { data: navFlow } = useQuery({
    queryKey: ["nav-flow", projectId],
    queryFn: async () => {
      const r = await fetch(
        `${API}/api/_debug/project-file/${projectId}/src/contracts/nav-flow.json`,
      );
      return r.ok ? r.json() : null;
    },
    enabled: !!projectId,
  });
  useEffect(() => {
    const pages: Array<{ id?: string }> = (navFlow as any)?.pages ?? [];
    if (!pages.length) return;
    if (pageSlug !== "home" && pages.some((p) => p.id === pageSlug)) return;
    const target = (navFlow as any)?.initialPage ?? pages[0]?.id;
    const pagesHaveHome = pages.some((p) => p.id === "home");
    if (target && target !== pageSlug) {
      setPageSlug(target);
      setOpenPages((prev) => {
        // Drop the placeholder "home" tab when the project has no real "home"
        // page (otherwise a dead tab lingers → "No schema at home.json").
        const cleaned = pagesHaveHome ? prev : prev.filter((s) => s !== "home");
        return cleaned.includes(target) ? cleaned : [...cleaned, target];
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navFlow]);

  // Attach the debounced auto-save subscriber for this project so every edit
  // (drop / move / delete / undo) persists to disk. Without this the store
  // mutates but nothing is written, and the Save button's flushPersister()
  // no-ops. Detaches on unmount / project change.
  useEffect(() => {
    const detach = attachPersister(projectId);
    return () => {
      // Flush any pending debounced save before detaching so an edit made just
      // before an SPA route change / project switch isn't dropped.
      void flushPersister();
      detach();
    };
  }, [projectId]);

  // Save handler — flush any pending debounced auto-save to disk, then mark
  // the editor state clean so the dirty indicator goes back to "Saved".
  // The toolbar's onClick wires here; persistence itself happens via the
  // debounced subscriber attached at session start.
  const handleSave = async () => {
    try {
      await flushPersister();
      markClean(); // also clears any prior saveError
    } catch (err) {
      // Surface the failure instead of swallowing it — the edit is still
      // unsaved (isDirty stays true because runSave threw before markClean).
      // eslint-disable-next-line no-console
      console.error("[VisualEditor] save failed:", err);
      setSaveError(
        "Couldn't save your changes. " + (err instanceof Error ? err.message : String(err)),
      );
    }
  };

  // Unsaved-changes guard: warn on tab close / reload while dirty, and flush the
  // debounced save on page hide so an edit inside the 500ms window isn't lost.
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (useEditorStore.getState().isDirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    const onPageHide = () => {
      if (useEditorStore.getState().isDirty) void flushPersister();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.removeEventListener("pagehide", onPageHide);
    };
  }, []);

  // Close drawers when viewport upgrades to desktop
  useEffect(() => {
    if (isDesktop) setOpenPanel(null);
  }, [isDesktop]);

  // Cmd/Ctrl+. toggles the right (properties) panel
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === ".") {
        e.preventDefault();
        setRightCollapsed((c) => !c);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const activatePage = (slug: string) => {
    setPageSlug(slug);
    setOpenPages((prev) => (prev.includes(slug) ? prev : [...prev, slug]));
    if (!isDesktop) setOpenPanel(null);
  };

  const closePage = (slug: string) => {
    setOpenPages((prev) => {
      const remaining = prev.filter((s) => s !== slug);
      if (slug === pageSlug && remaining.length > 0) {
        setPageSlug(remaining[remaining.length - 1]);
      }
      return remaining;
    });
  };

  const showPalette = isDesktop || openPanel === "palette";
  const showPages = isDesktop || openPanel === "pages";
  const showProperties = isDesktop || openPanel === "properties";

  // Nav-flow stores each page under BOTH `id` (kebab-case, editor-friendly:
  // "candidate-dashboard") and `route` (slash-separated URL: "/candidate/
  // dashboard"). The render-scaffold looks up schemas by file path — nested
  // pages live at `src/schemas/candidate/dashboard.json`, so the preview URL
  // must use `route`, not `id`. Fall back to `id` when no route is registered
  // (older projects, or the transient "home" placeholder before navFlow
  // arrives). Strip the leading slash so EditorToolbar can compose it as
  // `${PREVIEW_BASE}/p/${projectId}/${previewPage}` without double slashes.
  const previewPage = (() => {
    const pages: Array<{ id?: string; route?: string }> = (navFlow as any)?.pages ?? [];
    const entry = pages.find((p) => p.id === pageSlug);
    const route = entry?.route;
    if (typeof route === "string" && route.startsWith("/")) return route.slice(1);
    return pageSlug;
  })();

  return (
    <div className="flex flex-col h-full bg-background">
      {!hideToolbar && (
        <EditorToolbar
          projectId={projectId}
          device={device}
          onDeviceChange={setDevice}
          isDirty={isDirty}
          onSave={handleSave}
          currentPage={previewPage}
        />
      )}
      {!hidePageTabs && (
        <PageTabs
          openPages={openPages}
          activePage={pageSlug}
          onActivate={setPageSlug}
          onClose={closePage}
        />
      )}

      <div className="flex flex-1 overflow-hidden relative">
        {!isDesktop && openPanel && (
          <div
            className="absolute inset-0 bg-black/30 z-20"
            onClick={() => setOpenPanel(null)}
            aria-hidden="true"
          />
        )}

        {showPages && (
          <div
            className={
              isDesktop
                ? ""
                : "absolute z-30 top-0 left-0 bottom-0 bg-background shadow-xl"
            }
          >
            <PagePicker
              projectId={projectId}
              value={pageSlug}
              onChange={activatePage}
              collapsed={isDesktop && pagesCollapsed}
              onToggleCollapsed={() => setPagesCollapsed((c) => !c)}
            />
          </div>
        )}

        {showPalette && (
          <div
            className={
              isDesktop
                ? ""
                : "absolute z-30 top-0 left-0 bottom-0 bg-background shadow-xl"
            }
          >
            <Palette
              collapsed={isDesktop && paletteCollapsed}
              onToggleCollapsed={() => setPaletteCollapsed((c) => !c)}
            />
          </div>
        )}

        <main className="flex-1 overflow-auto bg-muted/30 relative">
          <Canvas projectId={projectId} pagePath={pageSlug} device={device} zoom={zoom} />
          <ZoomControls zoom={zoom} onChange={setZoom} />
        </main>

        {showProperties && (
          <div
            className={
              isDesktop
                ? ""
                : "absolute z-30 top-0 right-0 bottom-0 bg-background shadow-xl"
            }
          >
            <RightPanel
              collapsed={isDesktop && rightCollapsed}
              onToggleCollapsed={() => setRightCollapsed((c) => !c)}
            />
          </div>
        )}
      </div>

      <ErrorBanner />
    </div>
  );
}
