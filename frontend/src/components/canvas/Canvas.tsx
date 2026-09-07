"use client";
import { useRef, useEffect, useMemo, type CSSProperties, type DragEvent } from "react";
import { Plus } from "lucide-react";
import { Engine, EngineProvider } from "@tentoroforge/engine";
import { compileTokens, NavigatorProvider } from "@tentoroforge/renderer";
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
import { GridGuides } from "./GridGuides";
import { EmptyNodeHints } from "./EmptyNodeHints";
import { useEditorStore } from "@/lib/editor-store";
import { syntheticNodeId, migrateBindingsDeep } from "@forge/patches";
import { INERT_NAVIGATOR } from "@/lib/inert-navigator";

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
export function normaliseSchema(raw: any): any {
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
      // HEAL LEGACY BINDINGS ON THE WAY IN.
      //
      // The Bindings tab used to write `{ $binding: "expr" }`, a shape nothing
      // outside the editor implements — it reached React in child position and
      // rendered "⚠ render error", then autosaved itself into the page schema
      // and the generated app. The editor now writes "{{expr}}" instead, but
      // pages saved before that still carry the object on disk.
      //
      // This is the one production path every page load goes through, so
      // converting here means an affected page heals the moment it is opened,
      // with no migration script to run and nothing for the user to notice.
      // `migrateBindingsDeep` returns the same object when there is nothing to
      // change, so the common case costs a walk and no allocation. It must run
      // BEFORE `validateNoLegacyBindings` can reject the artifacts at commit.
      props: node.props ? migrateBindingsDeep(node.props) : node.props,
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
    // MERGED PER STEP, NOT PER RAMP.
    //
    // This used to spread `liveTokens.color` straight over `defaultTokens.color`,
    // which replaces a whole ramp object rather than merging into it. This
    // project's `tokens.custom.json` overrides exactly `color.primary = {50: …}`
    // (and `success = {50: …}`), so steps 100..950 of primary were ANNIHILATED:
    // measured on the canvas, `primary` emitted `[50]` while `secondary` and
    // `accent` emitted all eleven. `--token-color-primary-100` and `-500` were
    // undefined, so a Style-panel background referencing them painted nothing —
    // and two of the three primary options the panel offers were dead on arrival.
    const overrideColors = (liveTokens?.color as Record<string, unknown>) ?? {};
    const baseColors =
      (defaultTokens as { color?: Record<string, unknown> }).color ?? {};
    const mergedColors: Record<string, unknown> = { ...baseColors };
    for (const [ramp, value] of Object.entries(overrideColors)) {
      const base = baseColors[ramp];
      // Only ramps are objects; a flat colour (`color.foreground: "#000"`) still
      // overrides wholesale, which is correct for a scalar.
      mergedColors[ramp] =
        value && typeof value === "object" && !Array.isArray(value) &&
        base && typeof base === "object" && !Array.isArray(base)
          ? { ...(base as object), ...(value as object) }
          : value;
    }
    const merged = {
      ...(defaultTokens as Record<string, unknown>),
      color: mergedColors,
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
  //
  // `__authoring` is the EDITOR'S OPT-IN to seeing unresolved `{{…}}` bindings.
  // The renderer renders an unresolved binding as empty everywhere else — a
  // page whose `metrics` source doesn't exist used to ship
  // `{{metrics.list_total_inventory_value}}` as literal on-screen text to end
  // users, because "no data for this root" looks identical in a live app and on
  // an authoring canvas. Only this canvas wants the placeholder, so only this
  // canvas asks for it. It is a render-time flag on the data bag — it never
  // enters `store.artifacts`, so it cannot be autosaved into a page schema.
  const resolvedPreview = useMemo(
    () => ({
      ...resolvePreviewSources(activeSchema?.dataSources, previewData),
      __authoring: true,
    }),
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
      // Seed the editor token tree from the project's OVERRIDE file
      // (src/theme/tokens.custom.json, fetched as cssVarTokens). This is
      // deliberately overrides-only, NOT merged with defaultTokens: whatever
      // sits here is what persistence.ts writes straight back to
      // tokens.custom.json, so merging the defaults in would materialise the
      // whole library palette into every project's override file on the first
      // autosave. The TOKENS panel does that merge for display instead — see
      // TokenEditor's deepMerge. Fields the custom file omits default to {}
      // so `tokens` stays truthy and the panel skips its "No tokens loaded."
      // guard.
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
      // A GridCell is structure, not content. Dragging one out of (or around
      // inside) its grid would break the row-major addressing every other part
      // of the fixed-grid feature relies on — the cell count would stop matching
      // rows x columns and cell (1,2) would no longer be children[5]. The user
      // reorders what is INSIDE the cells; the cells themselves move only when
      // rows/columns change.
      if (el.hasAttribute("data-grid-cell")) return;
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
          <NavigatorProvider value={INERT_NAVIGATOR}>
            <EngineProvider designSpec={designSpec ?? {}} navFlow={navFlow} cssVarTokens={(liveTokens as Record<string, unknown>) ?? cssVarTokens}>
              <Engine schema={activeSchema} previewData={resolvedPreview} />
            </EngineProvider>
          </NavigatorProvider>
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
      <GridGuides canvasRef={canvasRef} />
      {/* Editor-only annotation of nodes that render nothing. Draws over the
          canvas and never into the schema, so it cannot reach a generated app —
          see EmptyNodeHints for why demo props were rejected in its place. */}
      <EmptyNodeHints canvasRef={canvasRef} />
      <SelectionOverlay canvasRef={canvasRef} />
      <DropIndicator hoverParent={hoverParent} canvasRef={canvasRef} />
      <ReorderIndicator indicator={reorder.indicator} canvasRef={canvasRef} />
    </>
  );
}
