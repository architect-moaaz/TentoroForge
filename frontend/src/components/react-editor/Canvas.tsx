"use client";
/**
 * The live canvas (CANVAS-001): the running application in a same-origin
 * iframe, with the editor's bridge injected on every load. Design mode
 * selects; Preview mode uses the app as people will. The bridge is the only
 * way in or out of the frame, and every message is checked against the
 * page's own origin (SYS-003).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ExternalLink, Loader2, Pencil, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { usePreview } from "@/hooks/usePreview";
import { cn } from "@/lib/utils";

import { InlineTextEditor } from "./InlineTextEditor";
import { plainName } from "./lib/plain";
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

/** The editor page a preview path belongs to, if any. */
export function pageForPath(path: string, pages: { id: string; route: string }[]): string | null {
  const clean = path.split("?")[0].replace(/\/$/, "") || "/";
  for (const p of pages) {
    const re = new RegExp("^" + p.route.replace(/\[[^\]]+\]/g, "[^/]+").replace(/\//g, "\\/") + "$");
    if (re.test(clean)) return p.id;
  }
  return null;
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
  const [reloadKey, setReloadKey] = useState(0);

  // Always the RELATIVE proxy path: Next rewrites /api/projects/* to the
  // backend, so the frame is same-origin and the bridge can be injected.
  const servePath = preview.servePath;
  const pageRoute = doc?.page.route ?? "/";
  const entryRoute = pages.find((p) => p.id === entryPage)?.route ?? "/";
  const { path: filledRoute, missing } = fillRoute(pageRoute, routeParams);
  const targetPath = previewApp ? entryRoute : filledRoute;
  const src = servePath && preview.port && !missing.length ? `${servePath}${targetPath === "/" ? "" : targetPath}` : null;

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

  // Messages from the bridge.
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== window.location.origin) return;
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
          break;
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
        case "navigate":
          setFrame({ previewPath: String(p.path ?? "") });
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

  // A record page needs a record: try the first row of its entity.
  const entityTable = useMemo(() => {
    const ent = doc?.entities.find((e) => (e as { table?: string }).table) as { table?: string } | undefined;
    return ent?.table ?? null;
  }, [doc]);
  useEffect(() => {
    if (!missing.length || !useEditorStore.getState().projectId || !entityTable) return;
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
  }, [doc?.page.id, entityTable, missing.join(",")]);

  const editingNode = editingTextId ? doc?.model?.nodes[editingTextId] : null;
  const editingRect = editingTextId ? rects[editingTextId] : null;
  const previewPageId = previewPath ? pageForPath(previewPath.replace(servePath ?? "", "") || "/", pages) : null;
  const scale = zoom;

  return (
    <div ref={containerRef} className="relative flex min-h-0 flex-1 flex-col">
      {/* Mode banner */}
      <div className={cn("flex h-8 shrink-0 items-center gap-2 px-3 text-xs",
        mode === "preview" ? "bg-emerald-600 text-white" : "bg-muted text-muted-foreground")}>
        {mode === "preview" ? (
          <>
            <span className="shrink-0 font-medium">{previewApp ? "Previewing the application" : "Previewing this page"}</span>
            <span className="min-w-0 truncate opacity-80">— buttons, forms and links work as they will for people. Data is the app's development data.</span>
            <div className="flex-1" />
            {previewApp && previewPageId && previewPageId !== doc?.page.id && (
              <Button size="xs" variant="secondary" onClick={() => { void openPage(previewPageId); setMode("design"); }}>
                <Pencil className="h-3 w-3" /> Edit this page
              </Button>
            )}
            <Button size="xs" variant="secondary" onClick={() => setMode("design")}>Back to design (Esc)</Button>
          </>
        ) : (
          <>
            <span className="font-medium text-foreground">Design</span>
            <span className="min-w-0 truncate">{regionSelect ? "Drag a box around the things you want to select." : "Click anything to select it. Double-click text to change it. Shift-click to select more."}</span>
            <div className="flex-1" />
            {missing.length > 0 && (
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
            <Button size="xs" variant="ghost" onClick={() => setReloadKey((k) => k + 1)} title="Reload the preview"><RefreshCw className="h-3 w-3" /></Button>
            {src && <a className="inline-flex h-6 items-center gap-1 px-2 hover:text-foreground" href={src} target="_blank" rel="noreferrer" title="Open in a new tab"><ExternalLink className="h-3 w-3" /></a>}
          </>
        )}
      </div>

      <div className="relative flex min-h-0 flex-1 items-start justify-center overflow-auto p-4" onClick={(e) => { if (e.target === e.currentTarget && mode === "design") select([]); }}>
        {!doc ? null : !doc.coded ? (
          <div className="mt-16 max-w-md rounded-xl border border-dashed border-border bg-card p-6 text-center">
            <p className="text-sm font-medium">This page has no designed code yet.</p>
            <p className="mt-1 text-sm text-muted-foreground">{doc.reason}</p>
          </div>
        ) : !preview.port ? (
          <div className="mt-16 max-w-md rounded-xl border border-border bg-card p-6 text-center">
            {preview.isStarting ? <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin text-muted-foreground" /> : null}
            <p className="text-sm font-medium">{preview.isStarting ? "Starting the application…" : "The application is not running."}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {preview.error ?? "The canvas shows your real application, so it needs to be running. This takes a few seconds."}
            </p>
            {!preview.isStarting && <Button className="mt-4" size="sm" onClick={() => void preview.startPreview()}>Start the app</Button>}
          </div>
        ) : missing.length ? (
          <div className="mt-16 max-w-md rounded-xl border border-border bg-card p-6 text-center">
            <p className="text-sm font-medium">This page shows one record.</p>
            <p className="mt-1 text-sm text-muted-foreground">Type the {missing.join(", ")} of a record above to design with real data, or ask Smith to change it without one.</p>
          </div>
        ) : (
          <div className="relative origin-top" style={{ transform: `scale(${scale})`, width: width, height: height }}>
            <div className={cn("overflow-hidden rounded-lg border border-border bg-white shadow-lg transition-[width] duration-200", device !== "desktop" && device !== "custom" && "rounded-[1.25rem] border-8 border-slate-800")}
              style={{ width, height }}>
              <iframe key={`${src}|${reloadKey}`} ref={iframeRef} src={src ?? "about:blank"} onLoad={() => void onLoad()}
                title="Application preview" className="h-full w-full border-0 bg-white"
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals" />
            </div>
            {editingNode && editingRect && mode === "design" && (
              <InlineTextEditor node={editingNode} rect={editingRect} onDone={() => setEditingTextId(null)} />
            )}
            {!frameReady && src && (
              <div className="pointer-events-none absolute left-1/2 top-4 -translate-x-1/2 rounded-full bg-background/90 px-3 py-1 text-xs text-muted-foreground shadow">
                <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Loading the page…
              </div>
            )}
          </div>
        )}
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
