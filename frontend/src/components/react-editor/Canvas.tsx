"use client";
/**
 * The live canvas (CANVAS-001): the page in a same-origin iframe with the
 * editor's bridge injected on every load. Two sources:
 *
 * - Instant (default): the page bundled on demand by the platform from the
 *   app's own node_modules, running its `load()` against sample data — no
 *   dev server, no database, no login (PREVIEW-004). A blob URL keeps the
 *   frame same-origin so the bridge can be injected.
 * - Live app: the app's dev server through the preview proxy, real data.
 *
 * Design mode selects; Preview mode uses the page as people will. The bridge
 * is the only way in or out of the frame, and every message is checked
 * against the frame's window (SYS-003).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ExternalLink, Loader2, Pencil, RefreshCw, Undo2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { usePreview } from "@/hooks/usePreview";
import { cn } from "@/lib/utils";

import { InlineTextEditor } from "./InlineTextEditor";
import { dropPosition } from "./lib/drop";
import { mainRoot, plainName } from "./lib/plain";
import { DEVICE_WIDTHS, useEditorStore } from "./store";
import type { Rect } from "./types";

const PREFIX = "forge-editor:";
let bridgeSource: Promise<string> | null = null;

function loadBridge(): Promise<string> {
  if (!bridgeSource) bridgeSource = fetch("/forge-editor-bridge.js").then((r) => r.text());
  return bridgeSource;
}

/** The page's route with its parameters filled from what the person chose. */
export function fillRoute(route: string, params: Record<string, string>): { path: string; missing: string[] } {
  const missing: string[] = [];
  const path = route.replace(/\[([^\]]+)\]/g, (_, k: string) => {
    const v = params[k];
    if (!v) missing.push(k);
    return encodeURIComponent(v ?? "");
  });
  return { path, missing };
}

/** The parameters a path gives a route, or null when it is not that route. */
export function matchRoute(path: string, route: string): Record<string, string> | null {
  const clean = path.split("?")[0].replace(/\/$/, "") || "/";
  const names: string[] = [];
  const base = route.replace(/\/$/, "") || "/";
  const re = new RegExp("^" + base.replace(/\[([^\]]+)\]/g, (_, k: string) => { names.push(k); return "([^/]+)"; }).replace(/\//g, "\\/") + "$");
  const m = re.exec(clean);
  if (!m) return null;
  const params: Record<string, string> = {};
  names.forEach((n, i) => { params[n] = decodeURIComponent(m[i + 1]); });
  return params;
}

/** The editor page a preview path belongs to, with its parameters and query. */
export function pageForPath(path: string, pages: { id: string; route: string }[]): { id: string; params: Record<string, string>; search: Record<string, string> } | null {
  const search: Record<string, string> = {};
  new URLSearchParams(path.split("?")[1] ?? "").forEach((v, k) => { search[k] = v; });
  // Static routes first, so /records/new is not read as /records/[id].
  const ordered = [...pages].sort((a, b) => Number(a.route.includes("[")) - Number(b.route.includes("[")));
  for (const p of ordered) {
    const params = matchRoute(path, p.route);
    if (params) return { id: p.id, params, search };
  }
  return null;
}

function frameHtml(css: string, vendorUrl: string, js: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}</style></head><body><div id="root"></div><script src="${vendorUrl}"></script><script>${js}</script></body></html>`;
}

export function Canvas({ preview }: { preview: ReturnType<typeof usePreview> }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const doc = useEditorStore((s) => s.doc);
  const pages = useEditorStore((s) => s.pages);
  const entryPage = useEditorStore((s) => s.entryPage);
  const mode = useEditorStore((s) => s.mode);
  const previewApp = useEditorStore((s) => s.previewApp);
  const regionSelect = useEditorStore((s) => s.regionSelect);
  const selection = useEditorStore((s) => s.selection);
  const select = useEditorStore((s) => s.select);
  const setRects = useEditorStore((s) => s.setRects);
  const labelsFor = useEditorStore((s) => s.labelsFor);
  const frameWidth = useEditorStore((s) => s.frameWidth);
  const device = useEditorStore((s) => s.device);
  const landscape = useEditorStore((s) => s.landscape);
  const zoom = useEditorStore((s) => s.zoom);
  const setZoom = useEditorStore((s) => s.setZoom);
  const routeParams = useEditorStore((s) => s.routeParams);
  const setRouteParam = useEditorStore((s) => s.setRouteParam);
  const frameReady = useEditorStore((s) => s.frameReady);
  const frameError = useEditorStore((s) => s.frameError);
  const previewPath = useEditorStore((s) => s.previewPath);
  const setFrame = useEditorStore((s) => s.setFrame);
  const openPage = useEditorStore((s) => s.openPage);
  const setMode = useEditorStore((s) => s.setMode);
  const editingTextId = useEditorStore((s) => s.editingTextId);
  const setEditingTextId = useEditorStore((s) => s.setEditingTextId);
  const rects = useEditorStore((s) => s.rects);
  const source = useEditorStore((s) => s.source);
  const setSource = useEditorStore((s) => s.setSource);
  const frameDoc = useEditorStore((s) => s.frameDoc);
  const vendor = useEditorStore((s) => s.vendor);
  const frameTarget = useEditorStore((s) => s.frameTarget);
  const frameLoading = useEditorStore((s) => s.frameLoading);
  const frameBuildError = useEditorStore((s) => s.frameBuildError);
  const loadFrame = useEditorStore((s) => s.loadFrame);
  const previewBack = useEditorStore((s) => s.previewBack);
  const previewStack = useEditorStore((s) => s.previewStack);
  const actions = useEditorStore((s) => s.actions);
  const [reloadKey, setReloadKey] = useState(0);

  const jit = source === "jit";
  // The live app is reached by the RELATIVE proxy path: Next rewrites
  // /api/projects/* to the backend, so the frame stays same-origin.
  const servePath = preview.servePath;
  const pageRoute = doc?.page.route ?? "/";
  const entryRoute = pages.find((p) => p.id === entryPage)?.route ?? "/";
  const { path: filledRoute, missing } = fillRoute(pageRoute, routeParams);
  const targetPath = previewApp ? entryRoute : filledRoute;
  const appSrc = servePath && preview.port && !missing.length ? `${servePath}${targetPath === "/" ? "" : targetPath}` : null;

  // The instant page lives at a blob URL of the parent's origin.
  const jitUrl = useMemo(() => {
    if (!jit || !frameDoc || !vendor) return null;
    return URL.createObjectURL(new Blob([frameHtml(frameDoc.css, vendor.url, frameDoc.js)], { type: "text/html" }));
  }, [jit, frameDoc, vendor]);
  useEffect(() => () => { if (jitUrl) URL.revokeObjectURL(jitUrl); }, [jitUrl]);
  const src = jit ? jitUrl : appSrc;

  // The app-wide preview starts at the entry page; leaving it returns to the open page.
  useEffect(() => {
    if (!jit || !doc?.coded) return;
    if (previewApp && entryPage) void loadFrame({ pageId: entryPage, params: {}, search: {} });
    else if (!previewApp && frameTarget && frameTarget.pageId !== doc.page.id) void loadFrame({ pageId: doc.page.id, params: {}, search: {} });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewApp, jit]);

  const width = frameWidth();
  const height = device === "custom" ? 900 : (landscape && device !== "desktop" ? DEVICE_WIDTHS[device].w : DEVICE_WIDTHS[device].h);

  const post = useCallback((type: string, payload: unknown = {}) => {
    const win = iframeRef.current?.contentWindow;
    if (!win) return;
    win.postMessage({ type: PREFIX + type, payload }, window.location.origin);
  }, []);

  // Inject the bridge on every document load of the frame.
  const onLoad = useCallback(async () => {
    const frame = iframeRef.current;
    if (!frame) return;
    setFrame({ frameReady: false, frameError: null });
    try {
      const d = frame.contentDocument;
      if (!d) throw new Error("The preview could not be reached.");
      if (!(d.defaultView as Window & { __forgeEditorBridge?: boolean })?.__forgeEditorBridge) {
        const s = d.createElement("script");
        s.textContent = await loadBridge();
        (d.head ?? d.documentElement).appendChild(s);
      }
    } catch (err) {
      setFrame({ frameError: err instanceof Error ? err.message : "The preview could not be reached." });
    }
  }, [setFrame]);

  // A drag that ends anywhere takes its landing hint with it.
  const dragComponent = useEditorStore((s) => s.dragComponent);
  useEffect(() => { if (!dragComponent) post("drop-hint", {}); }, [dragComponent, post]);

  // Messages from the frame: the bridge, and (instant) the page's own shims.
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.source !== iframeRef.current?.contentWindow) return;
      const d = e.data;
      if (!d || typeof d.type !== "string" || !d.type.startsWith(PREFIX)) return;
      const type = d.type.slice(PREFIX.length);
      const p = d.payload ?? {};
      const s = useEditorStore.getState();
      switch (type) {
        case "ready":
          setFrame({ frameReady: true, previewPath: String(p.path ?? "") });
          post("set-mode", { mode: s.mode === "preview" ? "preview" : s.regionSelect ? "region" : "design" });
          post("select", { fids: s.selection, labels: labelsFor(s.selection) });
          break;
        case "select":
          if (s.mode !== "design") break;
          if (!p.fid) { if (!p.shift) s.clearSelection(); break; }
          s.select([String(p.fid)], { extend: !!p.shift || !!p.meta, toggle: !!p.meta });
          if (!s.smith.open && !s.smith.pinned) s.setSmith({ open: true });
          // Selecting is how something is configured: its settings come with it.
          // A closed panel whose toggle had scrolled out of the top bar left
          // a selected component with nothing to set.
          if (!s.rightOpen) s.setRightOpen(true);
          break;
        case "drag-over": {
          // A palette item over the page: say where it would land.
          const model = s.doc?.model;
          if (s.mode !== "design" || !s.dragComponent || !model) { post("drop-hint", {}); break; }
          const node = p.fid ? model.nodes[String(p.fid)] : null;
          if (!node) { post("drop-hint", { fid: mainRoot(model), where: "inside" }); break; }
          post("drop-hint", { fid: node.id, where: dropPosition(node, Number(p.y ?? 1)) });
          break;
        }
        case "drop": {
          const comp = String(p.component || s.dragComponent || "");
          s.setDragComponent(null);
          post("drop-hint", {});
          if (s.mode !== "design" || !comp) break;
          const known = p.fid && s.doc?.model?.nodes[String(p.fid)] ? String(p.fid) : null;
          void s.dropComponent(comp, known, { y: Number(p.y ?? 1) });
          break;
        }
        case "region":
          if (Array.isArray(p.fids) && p.fids.length) { s.select(p.fids.map(String)); s.setSmith({ open: true }); }
          s.setRegionSelect(false);
          break;
        case "hover":
          s.setHovered(p.fid ? String(p.fid) : null);
          break;
        case "rects":
          setRects((p.rects ?? {}) as Record<string, Rect>, Number(p.scrollY ?? 0));
          break;
        case "edit-text": {
          const node = s.doc?.model?.nodes[String(p.fid)];
          if (node?.textEditable) { s.select([node.id]); s.setEditingTextId(node.id); }
          else if (node) toast.info(`The text of this ${plainName(node, s.doc?.registry).toLowerCase()} comes from data — ask Smith to change it.`);
          break;
        }
        case "navigate": {
          const path = String(p.path ?? "");
          setFrame({ previewPath: path });
          if (s.source !== "jit" || s.mode !== "preview") break;
          const hit = pageForPath(path, s.pages);
          if (!hit) { toast.info(`“${path}” is not a page of this application.`); break; }
          s.previewNavigate(hit.id, hit.params, hit.search, !!p.replace);
          break;
        }
        case "navigate-back":
          if (s.source === "jit") s.previewBack();
          break;
        case "action":
          s.recordAction({ at: Date.now(), workflow: String(p.workflow ?? ""), input: (p.input ?? {}) as Record<string, unknown>,
                           ok: !!p.ok, status: Number(p.status ?? 0), elapsedMs: Number(p.elapsedMs ?? 0), mocked: !!p.mocked, output: p.output });
          break;
        case "key":
          if (s.mode !== "design") break;
          if (p.key === "delete") void s.removeSelected();
          else if (p.key === "undo") void s.undo();
          else if (p.key === "redo") void s.redo();
          else if (p.key === "duplicate") void s.duplicateSelected();
          else if (p.key === "escape") { if (s.regionSelect) s.setRegionSelect(false); else s.clearSelection(); }
          else if (p.key === "arrowup") s.selectSibling(-1);
          else if (p.key === "arrowdown") s.selectSibling(1);
          else if (p.key === "arrowleft") s.selectParent();
          else if (p.key === "arrowright") s.selectChild();
          else if (p.key === "enter" && s.selection.length === 1) {
            const node = s.doc?.model?.nodes[s.selection[0]];
            if (node?.textEditable) s.setEditingTextId(node.id);
          }
          break;
        case "error":
          setFrame({ frameError: String(p.message ?? "This part could not load.") });
          break;
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [post, setFrame, setRects, labelsFor]);

  // Push mode and selection into the frame whenever they change.
  useEffect(() => {
    if (!frameReady) return;
    post("set-mode", { mode: mode === "preview" ? "preview" : regionSelect ? "region" : "design" });
  }, [mode, regionSelect, frameReady, post]);
  useEffect(() => {
    if (!frameReady) return;
    post("select", { fids: mode === "design" ? selection : [], labels: labelsFor(selection) });
  }, [selection, mode, frameReady, post, labelsFor, doc?.revision]);

  // Scroll the frame to a selection made elsewhere (layers, readiness).
  const lastScrolled = useRef<string>("");
  useEffect(() => {
    if (!frameReady || selection.length !== 1 || selection[0] === lastScrolled.current) return;
    lastScrolled.current = selection[0];
    const r = rects[selection[0]];
    const h = iframeRef.current?.clientHeight ?? 0;
    if (!r || r.top < 0 || r.top > h) post("scroll-to", { fid: selection[0] });
  }, [selection, frameReady, post, rects]);

  // Live app: a record page needs a record — try the first row of its entity.
  const entityTable = useMemo(() => {
    const ent = doc?.entities.find((e) => (e as { table?: string }).table) as { table?: string } | undefined;
    return ent?.table ?? null;
  }, [doc]);
  useEffect(() => {
    if (jit || !missing.length || !useEditorStore.getState().projectId || !entityTable) return;
    const projectId = useEditorStore.getState().projectId!;
    const token = localStorage.getItem("token");
    fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/projects/${projectId}/db/rows?table=${encodeURIComponent(entityTable)}&limit=1&offset=0`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {}, credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((out) => {
        const row = out?.rows?.[0];
        if (row?.id) for (const k of missing) if (!useEditorStore.getState().routeParams[k]) setRouteParam(k, String(row.id));
      })
      .catch(() => { /* no sample available — the person can type one */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc?.page.id, entityTable, missing.join(","), jit]);

  const editingNode = editingTextId ? doc?.model?.nodes[editingTextId] : null;
  const editingRect = editingTextId ? rects[editingTextId] : null;
  const shownPageId = jit ? frameTarget?.pageId ?? null : (previewPath ? pageForPath(previewPath.replace(servePath ?? "", "") || "/", pages)?.id ?? null : null);
  const shownPage = shownPageId ? pages.find((p) => p.id === shownPageId) : null;
  const lastAction = actions[actions.length - 1];
  const scale = zoom;
  const ready = jit ? !!frameDoc && !!vendor : !!preview.port;

  const frame = (
    <div className="relative origin-top" style={{ transform: `scale(${scale})`, width, height }}>
      <div className={cn("overflow-hidden rounded-lg border border-border bg-white shadow-lg transition-[width] duration-200", device !== "desktop" && device !== "custom" && "rounded-[1.25rem] border-8 border-slate-800")}
        style={{ width, height }}>
        <iframe key={`${src}|${reloadKey}`} ref={iframeRef} src={src ?? "about:blank"} onLoad={() => void onLoad()}
          title="Application preview" className="h-full w-full border-0 bg-white"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals" />
      </div>
      {editingNode && editingRect && mode === "design" && (
        <InlineTextEditor node={editingNode} rect={editingRect} onDone={() => setEditingTextId(null)} />
      )}
      {((!frameReady && src) || frameLoading) && (
        <div className="pointer-events-none absolute left-1/2 top-4 -translate-x-1/2 rounded-full bg-background/90 px-3 py-1 text-xs text-muted-foreground shadow">
          <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> {frameLoading ? (frameDoc ? "Updating the page…" : "Building the page…") : "Loading the page…"}
        </div>
      )}
    </div>
  );

  return (
    <div ref={containerRef} className="relative flex min-h-0 flex-1 flex-col">
      {/* Mode banner */}
      <div className={cn("flex h-8 shrink-0 items-center gap-2 px-3 text-xs",
        mode === "preview" ? "bg-emerald-600 text-white" : "bg-muted text-muted-foreground")}>
        {mode === "preview" ? (
          <>
            <span className="shrink-0 font-medium">{previewApp ? "Previewing the application" : "Previewing this page"}</span>
            <span className="min-w-0 truncate opacity-80">
              {jit ? "— sample data; buttons and forms run in preview only, nothing is saved." : "— the app's development data; saving is real."}
            </span>
            {jit && previewApp && previewStack.length > 0 && (
              <Button size="xs" variant="secondary" onClick={previewBack}><Undo2 className="h-3 w-3" /> Back</Button>
            )}
            {lastAction && (
              <span className="min-w-0 truncate rounded bg-white/15 px-1.5 py-0.5" title={JSON.stringify(lastAction.input)}>
                Ran “{doc?.workflows.find((w) => w.id === lastAction.workflow)?.name ?? lastAction.workflow}” in {lastAction.elapsedMs} ms{lastAction.mocked ? " (preview only)" : ""}
              </span>
            )}
            <div className="flex-1" />
            {shownPage && shownPage.id !== doc?.page.id && (
              <Button size="xs" variant="secondary" onClick={() => { void openPage(shownPage.id); setMode("design"); }}>
                <Pencil className="h-3 w-3" /> Edit “{shownPage.name}”
              </Button>
            )}
            <Button size="xs" variant="secondary" onClick={() => setMode("design")}>Back to design (Esc)</Button>
          </>
        ) : (
          <>
            <span className="font-medium text-foreground">Design</span>
            <span className="min-w-0 truncate">{regionSelect ? "Drag a box around the things you want to select." : "Click anything to select it. Double-click text to change it. Shift-click to select more."}</span>
            <div className="flex-1" />
            {jit ? (
              <span className="rounded bg-background px-1.5 py-0.5" title="The page is built on the spot with example records made from the app's data model. Switch to Live app to see real data.">Sample data</span>
            ) : missing.length > 0 && (
              <span className="flex items-center gap-1">
                Showing record
                {missing.map((k) => (
                  <Input key={k} className="h-6 w-40 text-xs" placeholder={`${k} of a record`} value={routeParams[k] ?? ""}
                    onChange={(e) => setRouteParam(k, e.target.value)} aria-label={`Record ${k}`} />
                ))}
              </span>
            )}
            <span className="tabular-nums">{Math.round(scale * 100)}%</span>
            <Button size="xs" variant="ghost" onClick={() => setZoom(scale - 0.1)} aria-label="Zoom out">−</Button>
            <Button size="xs" variant="ghost" onClick={() => setZoom(1)} aria-label="Actual size">1:1</Button>
            <Button size="xs" variant="ghost" onClick={() => setZoom(scale + 0.1)} aria-label="Zoom in">+</Button>
            <Button size="xs" variant="ghost" onClick={() => (jit ? void loadFrame(undefined, { fresh: true }) : setReloadKey((k) => k + 1))} title={jit ? "Rebuild the page" : "Reload the preview"}><RefreshCw className="h-3 w-3" /></Button>
            {!jit && appSrc && <a className="inline-flex h-6 items-center gap-1 px-2 hover:text-foreground" href={appSrc} target="_blank" rel="noreferrer" title="Open in a new tab"><ExternalLink className="h-3 w-3" /></a>}
          </>
        )}
      </div>

      <div className="relative flex min-h-0 flex-1 items-start justify-center overflow-auto p-4" onClick={(e) => { if (e.target === e.currentTarget && mode === "design") select([]); }}>
        {!doc ? null : !doc.coded ? (
          <div className="mt-16 max-w-md rounded-xl border border-dashed border-border bg-card p-6 text-center">
            <p className="text-sm font-medium">This page has no designed code yet.</p>
            <p className="mt-1 text-sm text-muted-foreground">{doc.reason}</p>
          </div>
        ) : jit && frameBuildError ? (
          <div className="mt-16 max-w-md rounded-xl border border-border bg-card p-6 text-center">
            <AlertTriangle className="mx-auto mb-2 h-5 w-5 text-amber-500" />
            <p className="text-sm font-medium">The page could not be built.</p>
            <p className="mt-1 text-sm text-muted-foreground">{frameBuildError}</p>
            <div className="mt-4 flex justify-center gap-2">
              <Button size="sm" onClick={() => void loadFrame(undefined, { fresh: true })}>Try again</Button>
              <Button size="sm" variant="outline" onClick={() => setSource("app")}>Use the live app instead</Button>
            </div>
          </div>
        ) : jit && !frameDoc ? (
          <div className="mt-16 max-w-md rounded-xl border border-border bg-card p-6 text-center">
            <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin text-muted-foreground" />
            <p className="text-sm font-medium">Building the page…</p>
            <p className="mt-1 text-sm text-muted-foreground">The first build of a page takes a few seconds; after that it is instant.</p>
          </div>
        ) : !jit && !preview.port ? (
          <div className="mt-16 max-w-md rounded-xl border border-border bg-card p-6 text-center">
            {preview.isStarting ? <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin text-muted-foreground" /> : null}
            <p className="text-sm font-medium">{preview.isStarting ? "Starting the application…" : "The application is not running."}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {preview.error ?? "Live app shows your real application with its real data, so it needs to be running. This takes a few seconds."}
            </p>
            {!preview.isStarting && (
              <div className="mt-4 flex justify-center gap-2">
                <Button size="sm" onClick={() => void preview.startPreview()}>Start the app</Button>
                <Button size="sm" variant="outline" onClick={() => setSource("jit")}>Use instant preview instead</Button>
              </div>
            )}
          </div>
        ) : !jit && missing.length ? (
          <div className="mt-16 max-w-md rounded-xl border border-border bg-card p-6 text-center">
            <p className="text-sm font-medium">This page shows one record.</p>
            <p className="mt-1 text-sm text-muted-foreground">Type the {missing.join(", ")} of a record above to design with real data, or switch to the instant preview, which uses a sample record.</p>
          </div>
        ) : ready ? frame : null}
        {frameError && (
          <div className="absolute bottom-3 left-3 right-3 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 shadow" role="alert">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="font-medium">This part of the page could not load.</div>
              <div className="truncate">{frameError}</div>
              <div className="mt-1">Undo your last change, or ask Smith to repair it.</div>
            </div>
            <button type="button" className="text-amber-700 hover:underline" onClick={() => setFrame({ frameError: null })}>Dismiss</button>
          </div>
        )}
      </div>
    </div>
  );
}
