"use client";
import * as React from "react";
import {
  renderNode,
  ClientStateContext,
  initialValues,
  nextValue,
  DialogStateProvider,
  useDialogState,
  ShellStateProvider,
  WorkflowDispatcherProvider,
  createWorkflowDispatch,
  useNavigator,
  type WorkflowDispatch,
} from "@tentoroforge/renderer";
import type { ClientAction, ClientStateValue } from "@tentoroforge/renderer";
import { buildDefaultRegistry } from "@tentoroforge/library";
import type { EngineProps, SchemaNode } from "./types";
import { fetchDataSources } from "./data/loader";
import { DesignSpecContext } from "./EngineProvider";
import { useNavigate } from "./nav/useNavigate";
import { useViewport, pickResponsiveValue, type Breakpoint } from "./responsive/useViewport";

// Context that exposes the active viewport breakpoint to any child that needs it.
export const ViewportContext = React.createContext<Breakpoint>("default");
export const useEngineViewport = () => React.useContext(ViewportContext);

function resolveTreeBreakpoint(node: any, bp: Breakpoint): any {
  if (!node || typeof node !== "object") return node;
  const props = node.props
    ? Object.fromEntries(
        Object.entries(node.props).map(([k, v]) => [k, pickResponsiveValue(v, bp)]),
      )
    : node.props;
  const children = Array.isArray(node.children)
    ? node.children.map((c: any) => resolveTreeBreakpoint(c, bp))
    : node.children;
  const slots =
    node.slots && typeof node.slots === "object"
      ? Object.fromEntries(
          Object.entries(node.slots).map(([k, arr]: any) => [
            k,
            Array.isArray(arr) ? arr.map((c: any) => resolveTreeBreakpoint(c, bp)) : arr,
          ]),
        )
      : node.slots;
  return { ...node, props, children, slots };
}

function synthesiseRoot(schema: EngineProps["schema"]): SchemaNode {
  if (schema?.root) return schema.root;
  // LLM agents occasionally emit `content: {...}` (shadcn / Next.js convention)
  // instead of the spec's `root: {...}`. Accept it as an alias so the page
  // renders instead of falling through to the empty-page placeholder. Backend
  // post-fix also rewrites `content` → `root` on disk; this is the runtime
  // safety net for schemas already in IndexedDB / cached on the client.
  const content = (schema as any)?.content;
  if (content && typeof content === "object" && (content as any).type) {
    return content as SchemaNode;
  }
  const tc = (schema as any)?.children;
  if (Array.isArray(tc) && tc.length > 0) {
    return { type: "Stack", id: "_synthetic_root", children: tc };
  }
  return {
    type: "Text",
    id: "_no_content",
    props: { content: "(empty page — open the editor to add content)" },
  };
}

/**
 * The main render entry point for generated apps + the editor canvas.
 * Fetches the schema's data sources, synthesises a root node if missing,
 * and dispatches through the renderer.
 *
 * Navigation: buttons with a NavActionDescriptor in their onClick prop are
 * rendered with `data-nav-trigger` / `data-nav-params` attributes (no JS
 * handler). A delegated click listener mounted here resolves the trigger
 * through useNavigate() (which consults NavFlowContext) and sets
 * window.location.href. This pattern avoids the renderer→library→engine
 * circular import: the library stays dependency-free from engine.
 */
/**
 * Outer Engine — provides cross-tree state (dialogs) so any descendant can
 * read/write without prop drilling. The inner EngineInner owns rendering.
 */
export function Engine(props: EngineProps) {
  return (
    <DialogStateProvider>
      <ShellStateProvider>
        <EngineInner {...props} />
      </ShellStateProvider>
    </DialogStateProvider>
  );
}

function EngineInner({ schema, apiBaseUrl = "", previewData, live }: EngineProps) {
  const [data, setData] = React.useState<Record<string, unknown>>(previewData ?? {});
  // THE SCREEN'S OWN VALUES ARE JUST ANOTHER BINDING SOURCE. A page declaring
  // `clientState` binds them as `{{state.display}}`, so they belong in the
  // same record every other binding resolves against — under `state`, which
  // is one word rather than each value at the top level, so a declared value
  // can never collide with a dataSource name.
  //
  // Held here rather than beside the tree because this record is what
  // `renderNode` reads: a value that changed somewhere the render did not see
  // would not repaint, which is the whole point of client state.
  const declaredState = (schema as { clientState?: ClientStateValue[] } | undefined)?.clientState;
  const [stateValues, setStateValues] = React.useState<Record<string, unknown>>(
    () => initialValues(declaredState));
  const runClientAction = React.useCallback((action: ClientAction) => {
    setStateValues((prev) => {
      const got = nextValue(action, prev);
      return got ? { ...prev, [got.target]: got.value } : prev;
    });
  }, []);
  const setClientValue = React.useCallback((name: string, value: unknown) => {
    setStateValues((prev) => ({ ...prev, [name]: value }));
  }, []);
  const clientState = React.useMemo(
    () => ({ values: stateValues, set: setClientValue, run: runClientAction }),
    [stateValues, setClientValue, runClientAction]);
  // A standalone app is live even when it ships server-resolved previewData;
  // only the editor/preview canvas (no `live`, with previewData) stays inert.
  const isLive = live ?? (previewData === undefined);

  // The navigation seam. A host app (dashboard layout) provides a router-backed
  // Navigator so post-submit redirects and refetches are soft (no full reload)
  // and routed modals (@modal slots) can react. Default = window.location.
  const nav = useNavigator();

  React.useEffect(() => {
    if (previewData !== undefined) { setData(previewData); return; }
    let cancelled = false;
    fetchDataSources(schema?.dataSources, apiBaseUrl).then(d => {
      if (!cancelled) setData(d);
    });
    return () => { cancelled = true; };
  }, [schema, apiBaseUrl, previewData]);

  // Re-fetch this page's data sources (e.g. after a workflow mutates data) so
  // the UI reflects the change without a full reload. No-op in editor/preview.
  const refetch = React.useCallback(() => {
    if (!isLive) return;
    // When data was resolved server-side (previewData), re-run the server
    // component to pick up the mutation; client-side dataSource fetching isn't
    // wired for those pages. Otherwise refetch the client dataSources in place.
    if (previewData !== undefined) {
      // nav.refresh() is router.refresh() under a host app (re-runs the server
      // component in place); falls back to a full reload with the default nav.
      nav.refresh();
      return;
    }
    fetchDataSources(schema?.dataSources, apiBaseUrl).then(setData);
  }, [schema, apiBaseUrl, previewData, isLive, nav]);

  // Workflow dispatcher — the renderer's Button/Form consume this context to
  // POST to /api/workflows/{name}/execute. Live apps dispatch for real and
  // refetch on success; the editor/preview canvas stays inert.
  const dispatch = React.useMemo<WorkflowDispatch>(() => {
    if (!isLive) return async () => {};
    return createWorkflowDispatch({
      apiBase: apiBaseUrl,
      // On a create/edit form, a successful submit should leave the form — go to
      // the collection (after create) or the record (after edit). Without this the
      // form just sits there and the create looks like it did nothing, even though
      // the row was written. Other pages refetch their data in place.
      onSuccess: () => {
        if (typeof window !== "undefined") {
          const p = window.location.pathname.replace(/\/+$/, "");
          // Leaving a create/edit form → go to the parent collection/record.
          // Under a routed modal this soft-navigates the parent, which resets
          // the @modal slot (closing the overlay); nav.refresh() then re-runs
          // the underlying list's server component so the new row appears.
          if (p.endsWith("/new")) { nav.push(p.slice(0, -4) || "/"); nav.refresh(); return; }
          if (p.endsWith("/edit")) { nav.push(p.slice(0, -5) || "/"); nav.refresh(); return; }
        }
        refetch();
      },
      onError: (name, message) => {
        if (typeof console !== "undefined") console.error(`[workflow:${name}] ${message}`);
      },
    });
  }, [isLive, apiBaseUrl, refetch, nav]);

  if (!schema) {
    return <div data-tentoro-engine-error="">Schema not provided.</div>;
  }

  // eslint-disable-next-line react-hooks/rules-of-hooks
  const designSpec = React.useContext(DesignSpecContext);
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const registry = React.useMemo(
    () => buildDefaultRegistry({
      register: designSpec?.register,
      illustrationBasePath: designSpec?.illustrationBasePath,
    }),
    [designSpec?.register, designSpec?.illustrationBasePath],
  );
  const root = synthesiseRoot(schema);

  // Responsive prop resolution ────────────────────────────────────────────────
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const bp = useViewport();
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const resolvedRoot = React.useMemo(() => resolveTreeBreakpoint(root, bp), [root, bp]);
  // ──────────────────────────────────────────────────────────────────────────

  // Delegated nav-trigger + dialog-open click listener ──────────────────────
  // useNavigate reads NavFlowContext (supplied by EngineProvider) and returns
  // a function: navigate(trigger, params) → { url } | null.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const navigate = useNavigate({ data, user: data.user as any });
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const dialogState = useDialogState();
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const rootRef = React.useRef<HTMLDivElement>(null);
  // eslint-disable-next-line react-hooks/rules-of-hooks
  React.useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const handleClick = (e: MouseEvent) => {
      const targetEl = e.target as HTMLElement;

      // Dialog open trigger — takes precedence so a button can both
      // navigate and open a dialog (only the dialog wins; that's the
      // common UX).
      const dialogTarget = targetEl.closest(
        "[data-dialog-open]",
      ) as HTMLElement | null;
      if (dialogTarget && dialogState) {
        const id = dialogTarget.getAttribute("data-dialog-open");
        if (id) {
          e.preventDefault();
          dialogState.openDialog(id);
          return;
        }
      }

      const target = targetEl.closest(
        "[data-nav-trigger]",
      ) as HTMLElement | null;
      if (!target) return;
      const trigger = target.getAttribute("data-nav-trigger");
      if (!trigger) return;
      let params: Record<string, unknown> = {};
      const rawParams = target.getAttribute("data-nav-params");
      if (rawParams) {
        try { params = JSON.parse(rawParams); } catch { /* ignore */ }
      }
      const result = navigate(trigger, params);
      if (result && typeof window !== "undefined") {
        e.preventDefault();
        nav.push(result.url);
      }
    };
    el.addEventListener("click", handleClick);
    return () => el.removeEventListener("click", handleClick);
  }, [navigate, dialogState, nav]);
  // ──────────────────────────────────────────────────────────────────────────

  // `state` is merged rather than stored in `data` so a dataSource refetch
  // (which replaces `data` wholesale) cannot wipe what is on the screen.
  const bound = React.useMemo(
    () => (declaredState?.length ? { ...data, state: stateValues } : data),
    [data, stateValues, declaredState]);

  return (
    <ViewportContext.Provider value={bp}>
      <WorkflowDispatcherProvider dispatch={dispatch}>
        <ClientStateContext.Provider value={clientState}>
          <div ref={rootRef}>
            {renderNode(resolvedRoot as any, { data: bound, user: bound.user as any, registry } as any)}
          </div>
        </ClientStateContext.Provider>
      </WorkflowDispatcherProvider>
    </ViewportContext.Provider>
  );
}
