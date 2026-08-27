"use client";

import { useEffect, useRef, useState } from "react";
import type { Registry, TokenGroups } from "@tentoroforge/library";
import { createEditorStore, type EditorStoreApi } from "./state/store";
import { selectCurrentPage, selectAnyDirty } from "./state/selectors";
import { buildSetProp, findNodeDeep } from "./state/mutations";
import { Palette } from "./panes/Palette/Palette";
import { Canvas } from "./panes/Canvas/Canvas";
import { Properties } from "./panes/Properties/Properties";
import { Tree } from "./panes/Tree/Tree";
import { Explorer } from "./panes/Explorer/Explorer";
import { TabStrip } from "./panes/Tabs/TabStrip";
import { Switcher } from "./panes/Switcher/Switcher";
import { Diff } from "./panes/Diff/Diff";
import { Toolbar } from "./chrome/Toolbar";
import { DndProvider } from "./dnd/DndContext";
import { useShortcuts } from "./keyboard/useShortcuts";
import { saveSchema, loadSchema, getTheme, saveTheme, getProjectCss } from "./save/api";
import { ImportModal } from "./panes/Figma/ImportModal";
import { ThemeEditor } from "./panes/Theme/ThemeEditor";
import { useAmbientSuggestions } from "./panes/AI/useAmbientSuggestions";
import { AISidebar } from "./panes/AI/AISidebar";
import { RegenerateModal } from "./panes/AI/RegenerateModal";
import { KeyboardHelp } from "./chrome/KeyboardHelp";
import { ToastProvider, useToast } from "./chrome/Toaster";
import { CustomEditor } from "./panes/Properties/CustomEditor";
import { useStore } from "zustand";
import { ChevronLeft, ChevronRight, Files, LayoutGrid } from "lucide-react";

export type EditorProps = {
  initialSchemaPath?: string;
  registry: Registry;
  tokens: TokenGroups;
  apiBaseUrl?: string;
};

// Outer wrapper provides ToastProvider so EditorContent can call useToast()
export function Editor(props: EditorProps) {
  return (
    <ToastProvider>
      <EditorContent {...props} />
    </ToastProvider>
  );
}

function EditorContent({ initialSchemaPath, registry, tokens, apiBaseUrl = "" }: EditorProps) {
  const storeRef = useRef<EditorStoreApi | null>(null);
  if (!storeRef.current) storeRef.current = createEditorStore();
  const store = storeRef.current;
  const { push: pushToast } = useToast();

  const currentPath = useStore(store, (s) => s.currentPath);
  const selectedNodeId = useStore(store, (s) => {
    const p = s.currentPath ? s.pages[s.currentPath] : null;
    return p?.selection.length === 1 ? p.selection[0] : null;
  });
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const [themeOpen, setThemeOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [regenerateOpen, setRegenerateOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [figmaImportOpen, setFigmaImportOpen] = useState(false);
  const [customEditingId, setCustomEditingId] = useState<string | null>(null);
  const [pagesCollapsed, setPagesCollapsed] = useState(false);
  const [paletteCollapsed, setPaletteCollapsed] = useState(false);

  // Selector: the currently selected node, only if it is a Custom node
  const selectedCustomNode = useStore(store, (s) => {
    const page = selectCurrentPage(s);
    if (!page || page.selection.length !== 1) return null;
    const node = findNodeDeep((page.schema as any).root, page.selection[0]);
    return node?.type === "Custom" ? node : null;
  });

  // Auto-close the drawer when selection moves away from a Custom node or page closes
  useEffect(() => {
    if (!customEditingId) return;
    const page = selectCurrentPage(store.getState());
    if (!page) {
      setCustomEditingId(null);
      return;
    }
    const node = findNodeDeep((page.schema as any).root, customEditingId);
    if (!node || node.type !== "Custom") {
      setCustomEditingId(null);
    }
  }, [currentPath, selectedCustomNode, customEditingId, store]);

  // Snapshot of the node being edited in the drawer (from the store at open-time identity)
  const customEditingNode = useStore(store, (s) => {
    if (!customEditingId) return null;
    const page = selectCurrentPage(s);
    if (!page) return null;
    return findNodeDeep((page.schema as any).root, customEditingId) ?? null;
  });

  function handleCustomSave(next: { html: string; tailwind: string; label?: string }) {
    if (!customEditingId) return;
    const page = selectCurrentPage(store.getState());
    if (!page) return;
    const current = findNodeDeep((page.schema as any).root, customEditingId);
    const currentProps = current?.props ?? {};

    // Only emit set-prop mutations for fields that actually changed
    const subs: ReturnType<typeof buildSetProp>[] = [];
    if (next.html !== (currentProps.html ?? "")) {
      subs.push(buildSetProp(customEditingId, "html", next.html, page.schema as any));
    }
    if (next.tailwind !== (currentProps.tailwind ?? "")) {
      subs.push(buildSetProp(customEditingId, "tailwind", next.tailwind, page.schema as any));
    }
    const nextLabel = next.label ?? "";
    const currentLabel = currentProps.label ?? "";
    if (nextLabel !== currentLabel) {
      subs.push(buildSetProp(customEditingId, "label", nextLabel || undefined, page.schema as any));
    }

    if (subs.length > 0) {
      store.getState().apply(
        subs.length === 1 ? subs[0] : { kind: "composite", mutations: subs }
      );
    }
    setCustomEditingId(null);
  }

  // beforeUnload guard — warn if any page has unsaved changes
  useEffect(() => {
    function handler(e: BeforeUnloadEvent) {
      if (selectAnyDirty(store.getState())) {
        e.preventDefault();
        e.returnValue = "";
      }
    }
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [store]);

  // Load theme on mount.
  // Default-source projects come back with empty `tokens`; in that case we
  // fall back to the `tokens` prop (the library's defaultTokens) so the canvas
  // gets the full design system as CSS variables. Without this the rendered
  // schema looks unstyled because no `--token-*` vars are emitted.
  useEffect(() => {
    let cancelled = false;
    const seed = (effective: typeof tokens, source: "default" | "custom") => {
      if (cancelled) return;
      store.getState().loadTheme(effective, source);
    };
    // Deep-merge custom tokens INTO defaults. Project-compiled tokens.custom.json
    // typically only covers color/typography (the design-spec sections that
    // landed in the planner output). Replacing the whole theme with custom
    // would drop spacing/radius/shadow back to undefined, leaving every
    // var(--token-radius-md) / var(--token-spacing-4) reference broken.
    const mergeTokens = (base: any, overlay: any): any => {
      if (overlay === null || overlay === undefined) return base;
      if (typeof overlay !== "object" || Array.isArray(overlay)) return overlay;
      const out: Record<string, any> = { ...(base || {}) };
      for (const [k, v] of Object.entries(overlay)) {
        out[k] = mergeTokens(out[k], v);
      }
      return out;
    };
    // Seed defaults synchronously so the canvas is styled on first paint.
    seed(tokens, "default");
    getTheme(apiBaseUrl)
      .then((r) => {
        if (r.source === "custom" && r.tokens && Object.keys(r.tokens).length > 0) {
          seed(mergeTokens(tokens, r.tokens), "custom");
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [apiBaseUrl, store, tokens]);

  // Fetch the project's compiled globals.css so the editor canvas can mount
  // the same stylesheet the generated app uses (HSL design tokens, base
  // styles, shadcn-style component primitives). The canvas then renders
  // pages identically to production rather than relying on hand-written
  // editor-side defaults. Tailwind directives like `@tailwind base` are
  // no-ops in the browser context — the HSL custom-property block, the
  // `:root` declarations, and any plain-CSS selectors still apply.
  const [projectCss, setProjectCss] = useState<string>("");
  useEffect(() => {
    let cancelled = false;
    getProjectCss(apiBaseUrl).then((css) => {
      if (!cancelled) setProjectCss(css);
    });
    return () => { cancelled = true; };
  }, [apiBaseUrl]);

  const theme = useStore(store, (s) => s.theme);

  // Compile CSS custom properties from theme tokens. Tokens nest arbitrarily
  // deep — e.g. defaultTokens.color.primary["500"] = "#3b82f6" — so we walk to
  // the leaf (string|number) and emit `--token-color-primary-500: #3b82f6`.
  // The previous two-level loop emitted `--token-primary: [object Object]`,
  // which left every component referencing `var(--token-color-primary-500)`
  // with no defined CSS variable, and the canvas looked unstyled.
  const themeCSS = theme
    ? (function walk(obj: unknown, path: string[]): string[] {
        if (obj === null || obj === undefined) return [];
        if (typeof obj === "string" || typeof obj === "number") {
          return [`--token-${path.join("-")}: ${obj};`];
        }
        if (typeof obj !== "object") return [];
        const out: string[] = [];
        for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
          out.push(...walk(v, [...path, k.replace(/\./g, "-")]));
        }
        return out;
      })(theme, []).join(" ")
    : "";

  // Load initial page if specified and not already loaded
  useEffect(() => {
    if (!initialSchemaPath) return;
    if (store.getState().pages[initialSchemaPath]) {
      store.getState().switchPage(initialSchemaPath);
      return;
    }
    loadSchema(initialSchemaPath, apiBaseUrl).then((r) => {
      store.getState().openPage(initialSchemaPath, r.schema);
    });
  }, [initialSchemaPath, apiBaseUrl, store]);

  async function handleOpenPage(path: string) {
    if (store.getState().pages[path]) {
      store.getState().switchPage(path);
      return;
    }
    const r = await loadSchema(path, apiBaseUrl);
    store.getState().openPage(path, r.schema);
  }

  async function handleSave() {
    const page = selectCurrentPage(store.getState());
    if (!page) return;
    store.getState().setSaveState("saving");
    const result = await saveSchema(page.schemaPath, page.schema, apiBaseUrl);
    if (result.ok) {
      store.getState().markSaved(result.savedSchema);
    } else {
      const errMsg = result.errors.map((e) => e.message).join("; ");
      store.getState().setSaveState("error", errMsg);
      pushToast({ title: `Save failed: ${errMsg}`, kind: "error" });
    }
  }

  async function handleSaveTheme() {
    const t = store.getState().theme;
    if (!t) return;
    await saveTheme(t, apiBaseUrl);
    store.getState().markThemeSaved();
  }

  useShortcuts(store, handleSave, {
    onOpenSwitcher: () => setSwitcherOpen(true),
    onToggleDiff: () => setDiffOpen((v) => !v),
    onToggleTheme: () => setThemeOpen((v) => !v),
    onToggleAI: () => setAiOpen((v) => !v),
    onToggleHelp: () => setHelpOpen((v) => !v),
    onOpenFigmaImport: () => setFigmaImportOpen(true),
  });

  // Ambient LLM suggestions — debounced, always on
  useAmbientSuggestions(store, apiBaseUrl, true);

  const isLayoutMode = currentPath?.startsWith("_layouts/") ?? false;

  // Banner: shown when a Custom node is selected but its drawer is not yet open
  const showCustomBanner =
    selectedCustomNode !== null && customEditingId !== selectedCustomNode?.id;

  return (
    <DndProvider store={store} registry={registry}>
      {themeCSS && <style>{`:root { ${themeCSS} }`}</style>}
      {/* Mount the project's compiled globals.css so the canvas matches
          production styling. Rendered after the editor's own theme block so
          its :root HSL tokens win when both define the same custom property. */}
      {projectCss && <style data-source="project-globals-css">{projectCss}</style>}
      <div className="flex flex-col h-full bg-background text-foreground">
        <Toolbar
          store={store}
          onSave={handleSave}
          onRegenerate={selectedNodeId ? () => setRegenerateOpen(true) : undefined}
        />
        <TabStrip store={store} />
        {isLayoutMode && (
          <div
            role="alert"
            className="border-b border-amber-300 bg-amber-50 px-3 py-1.5 text-xs text-amber-900"
          >
            Editing layout template — Slot nodes enabled
          </div>
        )}
        <div className="flex flex-1 overflow-hidden">
          {/* Pages column — collapsible. Collapsed: thin 32px strip. Expanded:
              fixed-height column with a sticky header + scrollable content. */}
          {pagesCollapsed ? (
            <button
              type="button"
              onClick={() => setPagesCollapsed(false)}
              title="Show pages"
              className="w-8 shrink-0 border-r border-gray-100 bg-background hover:bg-muted/50 flex flex-col items-center justify-start gap-2 py-3 text-muted-foreground hover:text-foreground transition-colors"
            >
              <ChevronRight className="h-4 w-4" />
              <Files className="h-4 w-4" />
            </button>
          ) : (
            <div className="w-[240px] shrink-0 flex flex-col border-r border-gray-100 bg-background overflow-hidden">
              <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 shrink-0">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Pages
                </span>
                <button
                  type="button"
                  onClick={() => setPagesCollapsed(true)}
                  title="Hide pages"
                  className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors -mr-1"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto">
                <Explorer store={store} apiBaseUrl={apiBaseUrl} onOpenPage={handleOpenPage} />
                {currentPath && <Tree store={store} />}
              </div>
            </div>
          )}
          {/* Components column — collapsible the same way. */}
          {paletteCollapsed ? (
            <button
              type="button"
              onClick={() => setPaletteCollapsed(false)}
              title="Show components"
              className="w-8 shrink-0 border-r border-gray-100 bg-muted/20 hover:bg-muted/50 flex flex-col items-center justify-start gap-2 py-3 text-muted-foreground hover:text-foreground transition-colors"
            >
              <ChevronRight className="h-4 w-4" />
              <LayoutGrid className="h-4 w-4" />
            </button>
          ) : (
            <div className="w-[240px] shrink-0 flex flex-col border-r border-gray-100 bg-muted/20 overflow-hidden">
              <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 shrink-0 bg-background">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Components
                </span>
                <button
                  type="button"
                  onClick={() => setPaletteCollapsed(true)}
                  title="Hide components"
                  className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors -mr-1"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto">
                <Palette registry={registry} layoutMode={isLayoutMode} />
              </div>
            </div>
          )}
          <div className="flex-1 flex overflow-hidden bg-muted/20">
            {currentPath ? (
              <Canvas store={store} registry={registry} />
            ) : (
              <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
                Open a page from the Explorer (or press <kbd className="mx-1 px-1.5 py-0.5 rounded border border-border bg-background text-[11px] font-mono">⌘P</kbd>) to start editing.
              </div>
            )}
          </div>
          {/* Right column: banner + Properties + optional Custom drawer */}
          <div className="flex flex-col shrink-0">
            {showCustomBanner && selectedCustomNode && (
              <div className="border-b border-border bg-muted px-3 py-1.5 text-xs flex items-center justify-between">
                <span>Custom block selected — Edit content</span>
                <button
                  type="button"
                  onClick={() => setCustomEditingId(selectedCustomNode.id)}
                  className="ml-2 px-2 py-0.5 rounded text-xs border border-border bg-background hover:bg-muted-foreground/10 cursor-pointer"
                >
                  Open editor
                </button>
              </div>
            )}
            {currentPath && (
              <Properties store={store} registry={registry} tokens={tokens} />
            )}
          </div>
          {customEditingId !== null && customEditingNode !== null && (
            <CustomEditor
              key={customEditingId}
              node={customEditingNode}
              onSave={handleCustomSave}
              onCancel={() => setCustomEditingId(null)}
            />
          )}
          {diffOpen && currentPath && (
            <div className="w-[320px] shrink-0 border-l border-border bg-background overflow-y-auto">
              <Diff store={store} />
            </div>
          )}
          {themeOpen && (
            <ThemeEditor store={store} onSave={handleSaveTheme} />
          )}
          {aiOpen && (
            <AISidebar store={store} />
          )}
        </div>
        {regenerateOpen && selectedNodeId && (
          <RegenerateModal
            store={store}
            nodeId={selectedNodeId}
            apiBaseUrl={apiBaseUrl}
            onClose={() => setRegenerateOpen(false)}
          />
        )}
        <Switcher
          open={switcherOpen}
          onClose={() => setSwitcherOpen(false)}
          onOpenPage={(path) => handleOpenPage(path)}
          apiBaseUrl={apiBaseUrl}
        />
        <KeyboardHelp open={helpOpen} onClose={() => setHelpOpen(false)} />
        <ImportModal
          open={figmaImportOpen}
          onClose={() => setFigmaImportOpen(false)}
          apiBaseUrl={apiBaseUrl}
          onImport={(schema, savePath) => {
            store.getState().openPage(savePath, schema);
            store.getState().switchPage(savePath);
          }}
        />
      </div>
    </DndProvider>
  );
}
