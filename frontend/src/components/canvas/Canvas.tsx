"use client";
import { useRef, useEffect, useMemo, type CSSProperties, type DragEvent } from "react";
import { Plus } from "lucide-react";
import { Engine, EngineProvider } from "@tentoroforge/engine";
import { compileTokens } from "@tentoroforge/renderer";
import { defaultTokens } from "@tentoroforge/library";
import { resolvePreviewSources } from "@/lib/preview-resolve";
import { useArtifacts } from "./hooks/useArtifacts";
import { useCanvasClick } from "./hooks/useSelection";
import { useCanvasDrop } from "./hooks/useDrop";
import { useCanvasReorder } from "./hooks/useReorder";
import { CanvasFrame } from "./CanvasFrame";
import { SelectionOverlay } from "./SelectionOverlay";
import { DropIndicator } from "./DropIndicator";
import { ReorderIndicator } from "./ReorderIndicator";
import { useEditorStore } from "@/lib/editor-store";
import { syntheticNodeId } from "@forge/patches";

/**
 * Recursively inject stable ids into every node that doesn't already have one.
 * Normalises the legacy "children at top level" format to { root: SchemaNode }.
 *
 * Uniqueness: syntheticNodeId hashes (type, props), so two structurally
 * identical siblings (e.g. empty <Card/>s) collide. We disambiguate by
 * tracking ids we've already emitted in this tree and suffixing duplicates
 * with the child path. Stability is preserved because the same input tree
 * always produces the same walk order, so the same nodes get the same
 * disambiguated ids each render.
 */
function normaliseSchema(raw: any): any {
  const seen = new Set<string>();
  function uniq(base: string, path: string): string {
    if (!seen.has(base)) { seen.add(base); return base; }
    let candidate = `${base}_${path || "root"}`;
    let n = 2;
    while (seen.has(candidate)) {
      candidate = `${base}_${path || "root"}_${n++}`;
    }
    seen.add(candidate);
    return candidate;
  }
  function injectIds(node: any, path: string = ""): any {
    if (!node) return node;
    const baseId = node.id ?? syntheticNodeId(node);
    const id = uniq(baseId, path);
    return {
      ...node,
      id,
      children: Array.isArray(node.children)
        ? node.children.map((c: any, i: number) =>
            injectIds(c, path ? `${path}.${i}` : `${i}`)
          )
        : undefined,
      slots: node.slots && typeof node.slots === "object"
        ? Object.fromEntries(
            Object.entries(node.slots).map(([k, arr]) => [
              k,
              Array.isArray(arr)
                ? (arr as any[]).map((c, i) =>
                    injectIds(c, path ? `${path}.${k}.${i}` : `${k}.${i}`)
                  )
                : arr,
            ])
          )
        : undefined,
    };
  }

  // Support both schema formats
  const root = raw.root
    ?? (Array.isArray(raw.children) && raw.children.length > 0
      ? { type: "Stack", id: "_synthetic_root", children: raw.children }
      : { type: "Text", id: "_no_content", props: { content: "(empty)" } });

  return { ...raw, root: injectIds(root) };
}

export interface CanvasProps {
  projectId: string;
  pagePath: string;
  device?: "mobile" | "tablet" | "desktop";
  /** Scale applied to the device frame. 1 = 100%. */
  zoom?: number;
}

export function Canvas({ projectId, pagePath, device = "desktop", zoom = 1 }: CanvasProps) {
  const { schema, designSpec, cssVarTokens, navFlow, previewData, isLoading } =
    useArtifacts(projectId, pagePath);
  const canvasRef = useRef<HTMLDivElement>(null);
  const onClick = useCanvasClick();
  const palette = useCanvasDrop();
  const reorder = useCanvasReorder();
  const setInitial = useEditorStore(s => s.setInitial);

  // Reorder consumes its own drag (existing node → new position); anything else
  // falls through to the palette add-a-component drag. Both share the single
  // container's drag handlers, so we fan out here.
  const onDragOver = (e: DragEvent) => {
    if (!reorder.onDragOver(e)) palette.onDragOver(e);
  };
  const onDragLeave = () => {
    reorder.onDragLeave();
    palette.onDragLeave();
  };
  const onDrop = (e: DragEvent) => {
    if (!reorder.onDrop(e)) palette.onDrop(e);
  };
  const hoverParent = palette.hoverParent;

  // Render from the LIVE edit store, not the fetched file. useArtifacts seeds
  // the store (setInitial below); every edit (drop/move/delete/undo) mutates
  // the store, so the canvas must read the store to reflect those edits. The
  // store schema is the normalised one (explicit node ids), so the renderer's
  // data-node-id attributes match what findNode/selection look up. Falls back
  // to the fetched schema only for the first paint before the store is seeded.
  const liveSchema = useEditorStore((s) => {
    const ps = s.artifacts?.pageSchemas;
    if (!ps) return null;
    if (s.currentPageId && ps[s.currentPageId]) return ps[s.currentPageId];
    return Object.values(ps)[0] ?? null;
  });

  // The editor's live token tree (seeded from the project's tokens + edited via
  // the Tokens tab). Feed this to EngineProvider so token edits re-render the
  // canvas, and compile it to --token-* CSS vars below.
  const liveTokens = useEditorStore((s) => s.artifacts?.tokens as Record<string, unknown> | undefined);

  // Inject --token-* CSS custom properties onto the canvas root so StyleSlot
  // styling resolves in the editor. The renderer's applyStyleSlot compiles
  // node.style token-refs to var(--token-spacing-4) etc.; the production app
  // injects these via compileTokens on <html>, but the editor canvas didn't —
  // so StyleSlot styling (both the Style tab and generated node.style) was
  // invisible here. Merge the project's live colors so background refs pick up
  // the real brand palette.
  const tokenCssVars = useMemo(() => {
    const merged = {
      ...(defaultTokens as Record<string, unknown>),
      color: {
        ...((defaultTokens as { color?: Record<string, unknown> }).color ?? {}),
        ...((liveTokens?.color as Record<string, unknown>) ?? {}),
      },
    };
    try {
      // compileTokens drops the OUTERMOST key level (it walks each group's
      // entries starting at --token-<name>, not --token-<group>-<name>).
      // Wrapping in { t } shifts our real groups (color/spacing/radius/…) down
      // a level so they survive as the segment — yielding --token-spacing-4 /
      // --token-color-primary-500, exactly what applyStyleSlot's tokenVar()
      // looks up. Verified against the built dist.
      return compileTokens({ t: merged } as never) as CSSProperties;
    } catch {
      return {} as CSSProperties;
    }
  }, [liveTokens]);

  // The editor Engine renders bindings against previewData, but the fixture
  // endpoint keys rows by ENTITY name while bindings use SOURCE names. Resolve
  // each page dataSource (list/get/aggregate/series) over the fixtures so KPI
  // tiles and charts show sample data instead of raw {{…}} / empty.
  const activeSchema = (liveSchema ?? schema) as any;
  const resolvedPreview = useMemo(
    () => resolvePreviewSources(activeSchema?.dataSources, previewData),
    [activeSchema, previewData],
  );

  useEffect(() => {
    if (!schema || !navFlow) return;
    // Normalise the schema (inject synthetic ids, wrap legacy children format
    // into { root }) before pushing into the store. This lets both
    // findNodeInArtifacts and applyAction locate nodes by the same id that
    // the renderer's data-node-id attributes use.
    const normalised = normaliseSchema(schema as any);
    const pageId: string = normalised.id ?? pagePath;
    const artifacts = {
      pageSchemas: { [pageId]: normalised },
      navFlow,
      // Seed the editor token tree from the project's REAL tokens
      // (src/theme/tokens.custom.json, fetched as cssVarTokens) so the Tokens
      // tab shows the project's actual colors/typography instead of empty
      // stubs. Fields the custom file omits default to {} so the TokenEditor
      // sections still render.
      tokens: {
        color: {}, typography: {}, spacing: {},
        radius: {}, shadow: {}, motion: {}, breakpoints: {},
        ...((cssVarTokens as Record<string, unknown>) ?? {}),
      },
    };
    setInitial(artifacts as any);
  }, [schema, navFlow, pagePath, cssVarTokens, setInitial]);

  // Make every rendered node a drag source for reorder. The Engine emits plain
  // DOM with data-node-id (no per-node React wrapper), so we set the native
  // `draggable` attribute here after each render. The page root is excluded —
  // it can't be moved. Re-runs whenever the rendered schema changes.
  useEffect(() => {
    const host = canvasRef.current;
    if (!host) return;
    const rootId = (activeSchema as any)?.root?.id;
    host.querySelectorAll<HTMLElement>("[data-node-id]").forEach((el) => {
      if (el.getAttribute("data-node-id") === rootId) return;
      // Library components are wrapped in a display:contents span (no layout
      // box), so setting draggable there does nothing — Chromium won't start a
      // native drag from a boxless element. Walk to the inner box and mark THAT
      // draggable; the reorder handler still resolves the node via closest().
      let target: HTMLElement = el;
      if (getComputedStyle(el).display === "contents") {
        const inner = el.querySelector<HTMLElement>(":scope > *");
        if (inner) target = inner;
      }
      target.setAttribute("draggable", "true");
    });
  }, [activeSchema]);

  if (isLoading) {
    return (
      <div className="p-12 text-muted-foreground">
        Loading {pagePath}…
      </div>
    );
  }

  if (!schema) {
    return (
      <div className="p-12 text-muted-foreground">
        No schema at {pagePath}.json
      </div>
    );
  }

  // Editor-canvas padding parity with the production renderer:
  // in production, PageOutlet wraps every page in `px-4 py-6 sm:px-6 sm:py-8 lg:px-8`
  // so it doesn't collide with the shell chrome. The editor canvas should
  // show the same margins so what you edit looks like what ships.
  // Shell pages get the full padding; the "shell" page itself + auth pages
  // render edge-to-edge (no shell wraps them).
  const isShellPage = pagePath === "shell";
  const navPage = (navFlow as any)?.pages?.find((p: any) => p.id === pagePath);
  const wrapsInShell = !isShellPage && (navPage?.shell ?? true);
  const editorPadding = wrapsInShell ? "px-4 py-6 sm:px-6 sm:py-8 lg:px-8" : "";

  // BUG-010: detect a genuinely empty page so we can show a helper instead of a
  // blank dotted grid (or the literal "(empty)" text node the normaliser emits).
  const _rootChildren = (activeSchema as any)?.root?.children;
  const isEmptyCanvas =
    !activeSchema ||
    (activeSchema as any)?.root?.id === "_no_content" ||
    (Array.isArray(_rootChildren) && _rootChildren.length === 0);

  return (
    <>
      <CanvasFrame device={device} zoom={zoom}>
        <div
          ref={canvasRef}
          onClick={onClick}
          onDragStart={reorder.onDragStart}
          onDragEnd={reorder.onDragEnd}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          data-canvas-root
          className={`${editorPadding} relative`}
          style={tokenCssVars}
        >
          <EngineProvider designSpec={designSpec ?? {}} navFlow={navFlow} cssVarTokens={(liveTokens as Record<string, unknown>) ?? cssVarTokens}>
            <Engine schema={activeSchema} previewData={resolvedPreview} />
          </EngineProvider>
          {isEmptyCanvas && (
            // pointer-events-none so drops still land on the canvas root below.
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 p-8 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl border-2 border-dashed border-muted-foreground/30 text-muted-foreground/60">
                <Plus className="h-5 w-5" />
              </div>
              <p className="text-sm font-medium text-muted-foreground">
                This page is empty
              </p>
              <p className="max-w-xs text-xs text-muted-foreground/70">
                Drag a component from the palette on the left onto the canvas to
                start building, or use the AI prompt to generate a layout.
              </p>
            </div>
          )}
        </div>
      </CanvasFrame>
      <SelectionOverlay canvasRef={canvasRef} />
      <DropIndicator hoverParent={hoverParent} canvasRef={canvasRef} />
      <ReorderIndicator indicator={reorder.indicator} canvasRef={canvasRef} />
    </>
  );
}
