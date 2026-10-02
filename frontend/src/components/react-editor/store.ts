/**
 * The editor's document engine on the client: the open page at a revision,
 * the selection, the mode, and a history of transactions that undo as wholes.
 *
 * Every edit goes to the backend as one transaction against the revision the
 * page was loaded at; the backend checks it and answers with the committed
 * revision and model, which replace what is held here. Nothing is edited
 * optimistically — the canvas is the running app, and it reloads from the
 * saved source — so what the editor shows is always what is saved (UX-007).
 */
import { create } from "zustand";
import { toast } from "sonner";

import { editorApi, failureOf, type JitBundle } from "./api";
import { breakpointForWidth, getGroupValue, setGroupValue } from "./lib/classes";
import { dropPosition, type DropWhere } from "./lib/drop";
import { colSpanFor, fieldLabel, fieldRemoval, reorderField, widthClassFor, withFieldSpan } from "./lib/fields";
import { pageSources } from "./lib/data";
import { listKeyFor } from "./lib/lists";
import { GROUPS, type GroupKind } from "./lib/templates";
import { mainRoot, plainName, topmost } from "./lib/plain";
import type { Breakpoint, Device, DraftResult, Finding, HistoryEntry, ModelNode, Navigation, Op, PageDoc, PageListItem, PageModel, Proposal, PropValue, ReadOptions, Rect, ThemeDoc, ThemePatch } from "./types";

export interface Snapshot { revision: string; view: string; load: string }
export interface HistoryOp { label: string; before: Snapshot; after: Snapshot }

export type SaveState = "saved" | "unsaved" | "saving" | "checking" | "failed";

/** The revision the person is looking at: the draft's when there is one. */
export function currentRevision(doc: PageDoc | null | undefined): string {
  return doc?.draft?.revision ?? doc?.revision ?? "";
}
export type Mode = "design" | "preview";
export type ViewLevel = "simple" | "advanced";
export type LeftTab = "pages" | "add" | "layers" | "theme";
/** Where the canvas gets the page: bundled on demand with sample data, or the app's own dev server. */
export type CanvasSource = "jit" | "app";

export interface FrameTarget { pageId: string; params: Record<string, string>; search: Record<string, string> }
/** A change shown on the page's DOM at once: text, classes or an attribute of an element. */
export interface LivePatch { fid: string; text?: string; className?: string; attr?: { name: string; value: string | null } }

/** The edits that can be shown on the page before it is rebuilt. */
export function livePatchesOf(ops: Op[]): LivePatch[] {
  const out: LivePatch[] = [];
  for (const o of ops) {
    if (o.op === "setText") out.push({ fid: o.id, text: o.text });
    else if (o.op === "setClasses") out.push({ fid: o.id, className: o.classes });
    else if (o.op === "setProp" && o.name !== "className" && /^[a-z][a-z-]*$/.test(o.name) && (o.value === null || o.value.kind === "string")) {
      out.push({ fid: o.id, attr: { name: o.name, value: o.value ? String(o.value.value ?? "") : null } });
    }
  }
  return out;
}

export interface FrameDoc extends FrameTarget { js: string; css: string; revision: string; vendorKey: string; ms: number; cached: boolean; warnings: string[] }

/** The shared script every instant page runs on, held once per app as a blob URL. */
export interface VendorScript { key: string; url: string; bytes: number }

export interface ActionTrace {
  at: number;
  workflow: string;
  input: Record<string, unknown>;
  ok: boolean;
  status: number;
  elapsedMs: number;
  mocked: boolean;
  output?: unknown;
}

export const DEVICE_WIDTHS: Record<Exclude<Device, "custom">, { w: number; h: number }> = {
  desktop: { w: 1280, h: 800 },
  tablet: { w: 768, h: 1024 },
  mobile: { w: 390, h: 844 },
};

export interface SmithState {
  open: boolean;
  pinned: boolean;
  expanded: boolean;
  prompt: string;
  annotation: string;
  proposal: Proposal | null;
  /** The selection a pending proposal was made for — a new selection never inherits it (SMITH-001). */
  proposalFor: string[];
  busy: boolean;
  error: string | null;
  controller: AbortController | null;
  log: Proposal[];
}

export interface EditorState {
  projectId: string | null;
  pages: PageListItem[];
  navigation: Navigation | null;
  entryPage: string | null;
  pageId: string | null;
  doc: PageDoc | null;
  loading: boolean;
  loadError: string | null;

  selection: string[];
  hovered: string | null;
  rects: Record<string, Rect>;
  frameScrollY: number;
  frameReady: boolean;
  frameError: string | null;
  previewPath: string | null;

  mode: Mode;
  previewApp: boolean;
  regionSelect: boolean;
  viewLevel: ViewLevel;
  device: Device;
  customWidth: number;
  landscape: boolean;
  zoom: number;
  routeParams: Record<string, string>;

  source: CanvasSource;
  /** The page the frame shows: the open page, or where the app-wide preview has moved to. */
  frameTarget: FrameTarget | null;
  frameDoc: FrameDoc | null;
  vendor: VendorScript | null;
  frameLoading: boolean;
  frameBuildError: string | null;
  previewStack: FrameTarget[];
  actions: ActionTrace[];

  saveState: SaveState;
  saveError: string | null;
  lastFindings: Finding[];
  serverFindings: Finding[];
  checkedRevision: string | null;
  checking: boolean;
  undoStack: HistoryOp[];
  redoStack: HistoryOp[];
  busy: boolean;

  leftTab: LeftTab;
  leftOpen: boolean;
  rightOpen: boolean;
  drawerTab: string;
  showCode: boolean;
  showHistory: boolean;
  showReadiness: boolean;
  editingTextId: string | null;
  /** The palette item being dragged — the canvas frame cannot read the drag's own data. */
  dragComponent: string | null;
  /** A guided kind (a chart, a number tile, a form) dropped on the page: its
   *  questions open at once, and the answer goes where it was dropped. */
  pendingGuide: { compId: string; parentId: string; index: number | null } | null;
  /** One field of the selected form, when a field rather than the form is what is chosen. */
  fieldSelection: { nodeId: string; name: string } | null;
  /** What the last edit looks like on the page right away, before the page is rebuilt. */
  livePatches: LivePatch[];
  /** The application's look, read when the Theme tab opens. */
  theme: ThemeDoc | null;
  themeLoading: boolean;
  /** A look change that arrived while another save was in flight — merged in
   *  and sent the moment the current one finishes, so it is never dropped. */
  pendingThemePatch: ThemePatch | null;

  smith: SmithState;

  // --- lifecycle
  init: (projectId: string) => Promise<void>;
  loadPages: () => Promise<void>;
  openPage: (pageId: string) => Promise<void>;
  reload: () => Promise<void>;

  // --- selection
  select: (ids: string[], opts?: { extend?: boolean; toggle?: boolean }) => void;
  clearSelection: () => void;
  /** Choose one field of a form (selecting the form with it), or none. */
  selectField: (nodeId: string, name: string | null) => void;
  loadTheme: () => Promise<void>;
  /** A change to the look: written to the design system, every page follows. */
  saveTheme: (patch: ThemePatch) => Promise<boolean>;
  setHovered: (id: string | null) => void;
  setRects: (rects: Record<string, Rect>, scrollY: number) => void;
  selectParent: () => void;
  selectChild: () => void;
  selectSibling: (dir: 1 | -1) => void;

  // --- editing
  applyOps: (ops: Op[], label: string, opts?: { reselect?: (model: PageModel) => string[] }) => Promise<boolean>;
  /** Everything edited since the last save, written as one revision. */
  save: () => Promise<boolean>;
  /** Unsaved edits dropped; the page as last saved. */
  discard: () => Promise<void>;
  setText: (id: string, text: string) => Promise<boolean>;
  setProp: (id: string, name: string, value: PropValue | null) => Promise<boolean>;
  setClasses: (id: string, classes: string) => Promise<boolean>;
  removeSelected: () => Promise<boolean>;
  duplicateSelected: () => Promise<boolean>;
  insertJsx: (jsx: string, imports: Op[], opts?: { parentId?: string; index?: number | null; afterId?: string; label?: string }) => Promise<boolean>;
  moveNode: (id: string, parentId: string, index: number | null) => Promise<boolean>;
  /** An element's width as a share of its parent's, from a dragged edge. */
  resizeNode: (id: string, share: number) => Promise<boolean>;
  /** The selection put inside a new container; a container taken away around what it holds. */
  groupSelected: (kind: GroupKind) => Promise<boolean>;
  ungroupSelected: () => Promise<boolean>;
  /** One of the element per item of a list the page loads (null: once again). */
  repeatNode: (id: string, source: string | null) => Promise<boolean>;
  /** A list of an entity's records added to what the page loads; the new key. */
  addList: (entityName: string) => Promise<string | null>;
  /** How a list is read: which rows, what order, how many. */
  setListOptions: (key: string, options: ReadOptions) => Promise<boolean>;
  /** Shown only to people with this role; the page loads who is signed in if it does not yet. */
  showOnlyForRole: (id: string, role: string) => Promise<boolean>;
  /** A form field moved before another (null: last), widened, or taken out. */
  reorderField: (nodeId: string, name: string, beforeName: string | null) => Promise<boolean>;
  setFieldSpan: (nodeId: string, name: string, full: boolean) => Promise<boolean>;
  removeField: (nodeId: string, name: string) => Promise<boolean>;
  setDragComponent: (id: string | null) => void;
  setPendingGuide: (guide: { compId: string; parentId: string; index: number | null } | null) => void;
  /** Add a palette item where it was dropped: on a layer or on the page. `targetId` null is the end of the page. */
  dropComponent: (compId: string, targetId: string | null, where: DropWhere | { y: number }) => Promise<boolean>;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
  restore: (revision: string) => Promise<void>;
  runCheck: () => Promise<void>;

  // --- view
  setMode: (mode: Mode) => void;
  setPreviewApp: (on: boolean) => void;
  setRegionSelect: (on: boolean) => void;
  setViewLevel: (level: ViewLevel) => void;
  setDevice: (device: Device) => void;
  setCustomWidth: (w: number) => void;
  setLandscape: (on: boolean) => void;
  setZoom: (z: number) => void;
  setRouteParam: (name: string, value: string) => void;
  setLeftTab: (tab: LeftTab) => void;
  setLeftOpen: (open: boolean) => void;
  setRightOpen: (open: boolean) => void;
  setDrawerTab: (tab: string) => void;
  setShowCode: (on: boolean) => void;
  setShowHistory: (on: boolean) => void;
  setShowReadiness: (on: boolean) => void;
  setEditingTextId: (id: string | null) => void;
  setFrame: (patch: Partial<Pick<EditorState, "frameReady" | "frameError" | "previewPath">>) => void;
  setSource: (source: CanvasSource) => void;
  loadFrame: (target?: FrameTarget, opts?: { fresh?: boolean }) => Promise<void>;
  previewNavigate: (pageId: string, params: Record<string, string>, search: Record<string, string>, replace?: boolean) => void;
  previewBack: () => void;
  recordAction: (action: ActionTrace) => void;
  clearActions: () => void;

  // --- smith
  setSmith: (patch: Partial<SmithState>) => void;
  askSmith: (prompt: string, annotation?: string, prior?: { question: string; choice: string }) => Promise<void>;
  cancelSmith: () => void;
  applyProposal: (allowScopeExpansion?: boolean) => Promise<void>;
  discardProposal: () => Promise<void>;

  // --- derived helpers
  frameWidth: () => number;
  breakpoint: () => Breakpoint;
  labelsFor: (ids: string[]) => Record<string, string>;
}

const PREFS_KEY = (projectId: string) => `react-editor:prefs:${projectId}`;

function readPrefs(projectId: string): Partial<Pick<EditorState, "viewLevel" | "device" | "customWidth" | "leftTab" | "rightOpen" | "zoom" | "source">> {
  try {
    const raw = localStorage.getItem(PREFS_KEY(projectId));
    return raw ? JSON.parse(raw) : {};
  } catch { return {}; }
}

function writePrefs(state: EditorState) {
  if (!state.projectId) return;
  try {
    localStorage.setItem(PREFS_KEY(state.projectId), JSON.stringify({
      viewLevel: state.viewLevel, device: state.device, customWidth: state.customWidth,
      leftTab: state.leftTab, rightOpen: state.rightOpen, zoom: state.zoom, source: state.source,
    }));
  } catch { /* private mode */ }
}

function snapshotOf(doc: PageDoc): Snapshot {
  return { revision: currentRevision(doc), view: doc.source?.view ?? "", load: doc.source?.load ?? "" };
}

/** The page after an edit on its draft, as the store holds it. */
function withDraft(doc: PageDoc, out: DraftResult): PageDoc {
  return { ...doc, model: out.model, source: out.source, draft: out.dirty ? { revision: out.draftRevision, base: out.revision } : null };
}

const emptySmith = (): SmithState => ({
  open: false, pinned: false, expanded: false, prompt: "", annotation: "", proposal: null, proposalFor: [],
  busy: false, error: null, controller: null, log: [],
});

export const useEditorStore = create<EditorState>((set, get) => ({
  projectId: null,
  pages: [],
  navigation: null,
  entryPage: null,
  pageId: null,
  doc: null,
  loading: false,
  loadError: null,

  selection: [],
  hovered: null,
  rects: {},
  frameScrollY: 0,
  frameReady: false,
  frameError: null,
  previewPath: null,

  mode: "design",
  previewApp: false,
  regionSelect: false,
  viewLevel: "simple",
  device: "desktop",
  customWidth: 1024,
  landscape: false,
  zoom: 1,
  routeParams: {},

  source: "jit",
  frameTarget: null,
  frameDoc: null,
  vendor: null,
  frameLoading: false,
  frameBuildError: null,
  previewStack: [],
  actions: [],

  saveState: "saved",
  saveError: null,
  lastFindings: [],
  serverFindings: [],
  checkedRevision: null,
  checking: false,
  undoStack: [],
  redoStack: [],
  busy: false,

  leftTab: "pages",
  leftOpen: true,
  rightOpen: true,
  drawerTab: "settings",
  showCode: false,
  showHistory: false,
  showReadiness: false,
  editingTextId: null,
  dragComponent: null,
  pendingGuide: null,
  fieldSelection: null,
  livePatches: [],
  theme: null,
  themeLoading: false,
  pendingThemePatch: null,

  smith: emptySmith(),

  // ------------------------------------------------------------------ lifecycle

  init: async (projectId) => {
    const prefs = readPrefs(projectId);
    // Another project has another shared script; let this one's go.
    const old = get().vendor;
    if (old && typeof URL.revokeObjectURL === "function" && old.url.startsWith("blob:")) URL.revokeObjectURL(old.url);
    set({ projectId, ...prefs, pages: [], pageId: null, doc: null, selection: [], undoStack: [], redoStack: [], theme: null,
          smith: emptySmith(), mode: "design", previewApp: false, loadError: null,
          vendor: null, frameTarget: null, frameDoc: null, frameBuildError: null, previewStack: [], actions: [] });
    await get().loadPages();
    const { pages, entryPage } = get();
    const first = pages.find((p) => p.coded && p.id === entryPage) ?? pages.find((p) => p.coded) ?? pages[0];
    if (first) await get().openPage(first.id);
  },

  loadPages: async () => {
    const { projectId } = get();
    if (!projectId) return;
    try {
      const out = await editorApi.pages(projectId);
      set({ pages: out.pages, entryPage: out.entryPage, navigation: out.navigation ?? null });
    } catch (err) {
      set({ loadError: failureOf(err).message });
    }
  },

  openPage: async (pageId) => {
    const { projectId } = get();
    if (!projectId) return;
    set({ loading: true, loadError: null, pageId, selection: [], hovered: null, rects: {}, undoStack: [], redoStack: [],
          smith: emptySmith(), serverFindings: [], checkedRevision: null, lastFindings: [], editingTextId: null,
          mode: "design", previewApp: false, regionSelect: false, routeParams: {},
          frameTarget: null, frameDoc: null, frameBuildError: null, previewStack: [], actions: [] });
    try {
      const doc = await editorApi.open(projectId, pageId);
      // The revision subscription below builds the instant canvas from it.
      set({ doc, loading: false, saveState: doc.draft ? "unsaved" : "saved", saveError: null });
    } catch (err) {
      set({ loading: false, loadError: failureOf(err).message, doc: null });
    }
  },

  reload: async () => {
    const { projectId, pageId, selection } = get();
    if (!projectId || !pageId) return;
    try {
      const doc = await editorApi.open(projectId, pageId);
      set({ doc, saveState: doc.draft ? "unsaved" : "saved", saveError: null, undoStack: [], redoStack: [],
            selection: selection.filter((id) => doc.model?.nodes[id]) });
    } catch (err) {
      set({ loadError: failureOf(err).message });
    }
  },

  // ------------------------------------------------------------------ selection

  select: (ids, opts = {}) => {
    const { doc, selection, smith } = get();
    const model = doc?.model;
    const valid = ids.filter((id) => model?.nodes[id]);
    let next: string[];
    if (opts.toggle) next = selection.includes(valid[0]) ? selection.filter((x) => x !== valid[0]) : [...selection, ...valid];
    else if (opts.extend) next = Array.from(new Set([...selection, ...valid]));
    else next = valid;
    if (model) next = topmost(model, next);
    const changed = next.join("|") !== selection.join("|");
    // A proposal made for another selection is never applied to this one.
    const smithPatch: Partial<SmithState> = changed && smith.proposal && smith.proposalFor.join("|") !== next.join("|")
      ? { proposal: null, proposalFor: [] } : {};
    set({ selection: next, editingTextId: null, fieldSelection: null, smith: { ...smith, ...smithPatch, open: next.length ? smith.open : smith.pinned && smith.open } });
  },

  clearSelection: () => get().select([]),
  selectField: (nodeId, name) => {
    const { selection } = get();
    if (selection.join("|") !== nodeId) get().select([nodeId]);
    set({ fieldSelection: name ? { nodeId, name } : null });
  },
  setHovered: (id) => set({ hovered: id }),
  setRects: (rects, scrollY) => set({ rects, frameScrollY: scrollY }),

  selectParent: () => {
    const { doc, selection } = get();
    const node = doc?.model?.nodes[selection[0]];
    if (node?.parent) get().select([node.parent]);
  },
  selectChild: () => {
    const { doc, selection } = get();
    const node = doc?.model?.nodes[selection[0]];
    if (node?.children[0]) get().select([node.children[0]]);
  },
  selectSibling: (dir) => {
    const { doc, selection } = get();
    const model = doc?.model;
    const node = model?.nodes[selection[0]];
    if (!model || !node?.parent) return;
    const sibs = model.nodes[node.parent].children;
    const at = sibs.indexOf(node.id) + dir;
    if (sibs[at]) get().select([sibs[at]]);
  },

  // ------------------------------------------------------------------ editing

  applyOps: async (ops, label, opts = {}) => {
    const { projectId, pageId, doc, busy } = get();
    if (!projectId || !pageId || !doc?.model || busy) return false;
    // An edit lands on the page's draft; nothing is saved until Save. What
    // it looks like is shown on the page at once; the rebuilt page follows.
    set({ busy: true, saveError: null, livePatches: livePatchesOf(ops) });
    const before = snapshotOf(doc);
    try {
      const out = await editorApi.draftApply(projectId, pageId, { baseRevision: doc.revision, ops });
      const nextDoc = withDraft(doc, out);
      const after = snapshotOf(nextDoc);
      const reselect = opts.reselect ? opts.reselect(out.model) : get().selection.filter((id) => out.model.nodes[id]);
      set((s) => ({
        doc: nextDoc, busy: false, saveState: out.dirty ? "unsaved" : "saved", lastFindings: [],
        undoStack: out.unchanged ? s.undoStack : [...s.undoStack, { label, before, after }].slice(-100),
        redoStack: out.unchanged ? s.redoStack : [],
        selection: topmost(out.model, reselect),
      }));
      return true;
    } catch (err) {
      const f = failureOf(err);
      if (f.code === "stale") {
        toast.warning("The page changed elsewhere — reloaded it. Try your change again.");
        set({ busy: false });
        await get().reload();
        return false;
      }
      if (f.status === 422) {
        set({ busy: false, lastFindings: f.findings ?? [] });
        const first = f.findings?.[0]?.plain;
        toast.error(f.message, { description: first ?? undefined, duration: 8000 });
        return false;
      }
      set({ busy: false, saveState: "failed", saveError: f.message });
      toast.error("Couldn't make that change.", { description: f.message });
      return false;
    }
  },

  save: async () => {
    const { projectId, pageId, doc, busy } = get();
    if (!projectId || !pageId || !doc?.draft || !doc.source || busy) return false;
    set({ busy: true, saveState: "checking", saveError: null });
    try {
      const out = await editorApi.apply(projectId, pageId, doc.revision, [], "Edits in the editor", doc.source);
      set((s) => ({
        doc: { ...doc, revision: out.revision, model: out.model, source: out.source, draft: null,
               history: out.history ? [...doc.history, out.history] : doc.history },
        busy: false, saveState: "saved", lastFindings: [],
        serverFindings: out.checked ? [] : s.serverFindings, checkedRevision: out.checked ? out.revision : s.checkedRevision,
      }));
      toast.success("Saved.");
      return true;
    } catch (err) {
      const f = failureOf(err);
      if (f.code === "stale") {
        toast.warning("The page changed elsewhere since you opened it. Reloaded — your unsaved edits are kept aside; apply them again.");
        set({ busy: false, saveState: "saved" });
        await get().reload();
        return false;
      }
      if (f.status === 422) {
        set({ busy: false, saveState: "unsaved", lastFindings: f.findings ?? [] });
        toast.error("Not saved — something on the page would not work.", { description: f.findings?.[0]?.plain, duration: 10000 });
        return false;
      }
      set({ busy: false, saveState: "failed", saveError: f.message });
      toast.error("Couldn't save.", { description: f.message });
      return false;
    }
  },

  discard: async () => {
    const { projectId, pageId, doc } = get();
    if (!projectId || !pageId || !doc?.draft) return;
    try { await editorApi.discardDraft(projectId, pageId); } catch (err) { toast.error(failureOf(err).message); return; }
    set({ undoStack: [], redoStack: [] });
    await get().reload();
  },

  setText: (id, text) => get().applyOps([{ op: "setText", id, text }], "Change text"),
  setProp: (id, name, value) => get().applyOps([{ op: "setProp", id, name, value }], `Change ${name}`),
  setClasses: (id, classes) => get().applyOps([{ op: "setClasses", id, classes }], "Change look"),

  removeSelected: async () => {
    const { doc, selection, fieldSelection } = get();
    const model = doc?.model;
    if (!model || !selection.length) return false;
    if (fieldSelection) return get().removeField(fieldSelection.nodeId, fieldSelection.name);
    const ids = selection.filter((id) => model.nodes[id]?.parent);
    if (!ids.length) { toast.info("The page itself cannot be removed."); return false; }
    const parent = model.nodes[ids[0]].parent!;
    const names = ids.map((id) => plainName(model.nodes[id], doc?.registry)).join(", ");
    return get().applyOps([{ op: "remove", ids }], `Remove ${names}`, { reselect: (m) => (m.nodes[parent] ? [parent] : []) });
  },

  duplicateSelected: async () => {
    const { doc, selection } = get();
    const model = doc?.model;
    const node = model?.nodes[selection[0]];
    if (!model || !node?.parent) return false;
    const parent = node.parent;
    const at = node.index + 1;
    return get().applyOps([{ op: "duplicate", id: node.id }], `Duplicate ${plainName(node, doc?.registry)}`,
                          { reselect: (m) => [m.nodes[parent]?.children[at]].filter(Boolean) as string[] });
  },

  insertJsx: async (jsx, imports, opts = {}) => {
    const { doc, selection } = get();
    const model = doc?.model;
    if (!model) return false;
    let op: Op;
    let locate: (m: PageModel) => string[];
    if (opts.afterId) {
      const ref = model.nodes[opts.afterId];
      const parent = ref?.parent ?? mainRoot(model)!;
      const at = (ref?.index ?? -1) + 1;
      op = { op: "insert", afterId: opts.afterId, jsx };
      locate = (m) => [m.nodes[parent]?.children[at]].filter(Boolean) as string[];
    } else {
      const parentId = opts.parentId ?? selection[0] ?? mainRoot(model)!;
      const parent = model.nodes[parentId];
      const index = opts.index ?? null;
      const at = index ?? parent?.children.length ?? 0;
      op = { op: "insert", parentId, index, jsx };
      locate = (m) => [m.nodes[parentId]?.children[at]].filter(Boolean) as string[];
    }
    return get().applyOps([...imports, op], opts.label ?? "Add", { reselect: locate });
  },

  setDragComponent: (dragComponent) => set({ dragComponent }),
  setPendingGuide: (pendingGuide) => set({ pendingGuide }),

  dropComponent: async (compId, targetId, whereOrY) => {
    const { doc } = get();
    const model = doc?.model;
    const def = doc?.registry.components.find((c) => c.id === compId);
    if (!model || !def || def.status !== "ready") return false;
    const target = targetId ? model.nodes[targetId] : null;
    const where: DropWhere = !target ? "inside" : typeof whereOrY === "string" ? whereOrY : dropPosition(target, whereOrY.y);
    const parentId = !target ? mainRoot(model)! : where === "inside" ? target.id : target.parent!;
    const index = !target || where === "inside" ? null : target.index + (where === "after" ? 1 : 0);
    if (def.guide) {
      // A guided kind asks its questions first — HERE, the moment it lands,
      // and the answer goes where it was dropped. It used to select the
      // target, switch to Add and toast "click it in Add": a drop that put
      // nothing on the page and asked the person to do it again (NK,
      // 2026-09-22: "when I drag and drop the chart I cannot see it").
      get().select([parentId]);
      set({ pendingGuide: { compId, parentId, index } });
      return false;
    }
    return get().insertJsx(def.jsx, def.imports.map((i) => ({ op: "addImport", source: i.source, names: i.names }) as Op),
                           { parentId, index, label: `Add ${def.label.toLowerCase()}` });
  },

  moveNode: async (id, parentId, index) => {
    const { doc } = get();
    const model = doc?.model;
    const node = model?.nodes[id];
    if (!model || !node) return false;
    let at = index ?? model.nodes[parentId]?.children.length ?? 0;
    if (node.parent === parentId && index != null && index > node.index) at -= 1;
    return get().applyOps([{ op: "move", id, parentId, index }], `Move ${plainName(node, doc?.registry)}`,
                          { reselect: (m) => [m.nodes[parentId]?.children[at]].filter(Boolean) as string[] });
  },

  resizeNode: async (id, share) => {
    const { doc } = get();
    const model = doc?.model;
    const node = model?.nodes[id];
    if (!model || !node) return false;
    const classProp = node.props.find((p) => p.name === "className");
    if (classProp && classProp.value === null) { toast.info("This item's look is decided by code as the app runs — ask Smith to change it."); return false; }
    const classes = classProp?.value ?? "";
    const parent = node.parent ? model.nodes[node.parent] : null;
    const parentClasses = parent?.props.find((p) => p.name === "className")?.value ?? "";
    // In a grid, width is whole columns; anywhere else, a share of the row.
    const cols = /^grid-cols-(\d+)$/.exec(getGroupValue(parentClasses, "gridCols", "") ?? "");
    const next = cols
      ? setGroupValue(classes, "colSpan", "", `col-span-${colSpanFor(share, Number(cols[1]))}`)
      : setGroupValue(classes, "width", "", widthClassFor(share));
    if (next === classes) return false;
    return get().applyOps([{ op: "setClasses", id, classes: next }], `Resize ${plainName(node, doc?.registry)}`);
  },

  loadTheme: async () => {
    const { projectId } = get();
    if (!projectId) return;
    set({ themeLoading: true });
    try { set({ theme: await editorApi.theme(projectId) }); }
    catch (err) { toast.error(failureOf(err).message); }
    finally { set({ themeLoading: false }); }
  },
  saveTheme: async (patch) => {
    const { projectId, busy } = get();
    if (!projectId) return false;
    // Something else is mid-save (another colour's blur, a page edit — one
    // shared `busy`). Dropping this silently lost real edits (a colour typed
    // right after another looked unchanged); merged in and sent as soon as
    // the in-flight save clears, instead.
    if (busy) {
      set((s) => ({ pendingThemePatch: { ...s.pendingThemePatch, ...patch, colors: { ...s.pendingThemePatch?.colors, ...patch.colors } } }));
      return false;
    }
    set({ busy: true });
    try {
      const theme = await editorApi.setTheme(projectId, patch);
      set({ theme });
      // The look is part of every page: the canvas is built again with it.
      void get().loadFrame(undefined, { fresh: true });
      return true;
    } catch (err) {
      toast.error(failureOf(err).message);
      return false;
    } finally {
      set({ busy: false });
      const pending = get().pendingThemePatch;
      if (pending) { set({ pendingThemePatch: null }); void get().saveTheme(pending); }
    }
  },

  groupSelected: async (kind) => {
    const { doc, selection } = get();
    const model = doc?.model;
    const g = GROUPS.find((x) => x.kind === kind);
    if (!model || !g) return false;
    const nodes = selection.map((id) => model.nodes[id]).filter((n): n is ModelNode => !!n && !!n.parent);
    if (!nodes.length) { toast.info("Select what to group first."); return false; }
    const parent = nodes[0].parent!;
    if (nodes.some((n) => n.parent !== parent)) { toast.info("Group things that sit next to each other in the same container."); return false; }
    const at = Math.min(...nodes.map((n) => n.index));
    return get().applyOps([...g.imports, { op: "wrap", ids: nodes.map((n) => n.id), open: g.open, close: g.close }],
                          `Group into ${g.label.toLowerCase()}`, { reselect: (m) => [m.nodes[parent]?.children[at]].filter(Boolean) as string[] });
  },
  ungroupSelected: async () => {
    const { doc, selection } = get();
    const model = doc?.model;
    const node = model?.nodes[selection[0]];
    if (!model || !node || selection.length !== 1) { toast.info("Select one group to take apart."); return false; }
    if (!node.parent || !node.children.length) { toast.info("There is nothing inside it to keep — remove it instead."); return false; }
    const parent = node.parent;
    const at = node.index;
    const lifted = (m: PageModel, count: number) => (m.nodes[parent]?.children ?? []).slice(at, at + count);
    // A card holds its things in a CardContent: both come off.
    const twice = node.type === "Card" && node.children.length === 1 && model.nodes[node.children[0]]?.type === "CardContent";
    const inner = twice ? model.nodes[node.children[0]] : node;
    const ok = await get().applyOps([{ op: "unwrap", id: node.id }], `Ungroup ${plainName(node, doc?.registry)}`,
                                    { reselect: (m) => (twice ? [m.nodes[parent]?.children[at]].filter(Boolean) as string[] : lifted(m, node.children.length)) });
    if (!ok || !twice) return ok;
    const again = get().doc?.model?.nodes[parent]?.children[at];
    if (!again) return ok;
    return get().applyOps([{ op: "unwrap", id: again }], "Ungroup card", { reselect: (m) => lifted(m, inner.children.length) });
  },

  repeatNode: async (id, source) => {
    const { doc } = get();
    const node = doc?.model?.nodes[id];
    if (!node) return false;
    if (!source) return node.repeat ? get().applyOps([{ op: "unwrapRepeat", id }], `Show ${plainName(node, doc?.registry)} once`) : false;
    const parentId = node.parent!;
    const at = node.index;
    return get().applyOps([{ op: "wrapRepeat", id, source, variable: "row" }], `Repeat ${plainName(node, doc?.registry)} for each item`,
                          { reselect: (m) => [m.nodes[parentId]?.children[at]].filter(Boolean) as string[] });
  },
  addList: async (entityName) => {
    const { doc } = get();
    const model = doc?.model;
    const entity = doc?.entities.find((e) => e.name === entityName);
    if (!model || !entity) return null;
    const key = listKeyFor(entity.name, model.loadKeys);
    const ok = await get().applyOps([
      { op: "addImport", file: "load", source: "@/sdk/server", names: ["list"] },
      { op: "addReturnKey", file: "load", key, expr: `await list(${JSON.stringify(entity.name)})`,
        type: `Entities[${JSON.stringify(entity.name)}][]`, typeSource: "@/sdk/schema", fallback: "[]" },
    ], `Load the list of ${entity.name.toLowerCase()} records`);
    return ok ? key : null;
  },
  setListOptions: async (key, options) => {
    const { doc } = get();
    if (!doc?.model?.loadKeys.includes(key)) return false;
    return get().applyOps([{ op: "setReadOptions", file: "load", key, options }], "Change how the list is read");
  },

  showOnlyForRole: async (id, role) => {
    const { doc } = get();
    const model = doc?.model;
    if (!model || !model.nodes[id]) return false;
    let user = pageSources(doc).find((s) => s.shape.kind === "user");
    if (!user) {
      const key = model.loadKeys.includes("me") ? "signedIn" : "me";
      const ok = await get().applyOps([
        { op: "addReturnKey", file: "load", key, expr: "{ctx}.user", type: 'PageContext["user"]', typeSource: "@/sdk/server", fallback: "null" },
      ], "Load who is signed in");
      if (!ok) return false;
      user = pageSources(get().doc!).find((s) => s.shape.kind === "user");
      if (!user) return false;
    }
    return get().applyOps([{ op: "wrapCondition", id, expr: `${user.expr}?.role === ${JSON.stringify(role)}` }], `Only for ${role}`);
  },

  reorderField: async (nodeId, name, beforeName) => {
    const { doc } = get();
    const node = doc?.model?.nodes[nodeId];
    const entries = node?.objects?.fields;
    if (!node || !entries) return false;
    const next = reorderField(entries, name, beforeName);
    if (next === entries) return false;
    const ok = await get().applyOps([{ op: "setObjectProp", id: nodeId, name: "fields", entries: next }], `Move field ${fieldLabel(entries, name)}`);
    if (ok) set({ fieldSelection: { nodeId, name } });
    return ok;
  },
  setFieldSpan: async (nodeId, name, full) => {
    const { doc } = get();
    const node = doc?.model?.nodes[nodeId];
    const entries = node?.objects?.fields;
    if (!node || !entries) return false;
    const ok = await get().applyOps([{ op: "setObjectProp", id: nodeId, name: "fields", entries: withFieldSpan(entries, name, full) }],
                                    `${fieldLabel(entries, name)} ${full ? "across the row" : "half the row"}`);
    if (ok) set({ fieldSelection: { nodeId, name } });
    return ok;
  },
  removeField: async (nodeId, name) => {
    const { doc } = get();
    const node = doc?.model?.nodes[nodeId];
    const entries = node?.objects?.fields;
    if (!node || !entries) return false;
    const key = node.props.find((p) => p.name === "workflow")?.value?.replace(/^workflows\./, "");
    const input = doc?.workflows.find((w) => w.key === key)?.inputs.find((i) => i.name === name) ?? null;
    const out = fieldRemoval(entries, name, input);
    if ("refused" in out) { toast.info(out.refused); return false; }
    const ok = await get().applyOps([{ op: "setObjectProp", id: nodeId, name: "fields", entries: out.entries }], `Remove field ${fieldLabel(entries, name)}`);
    if (ok) set({ fieldSelection: null });
    return ok;
  },

  undo: async () => {
    const { projectId, pageId, doc, undoStack, busy } = get();
    const op = undoStack[undoStack.length - 1];
    if (!projectId || !pageId || !doc || !op || busy) return;
    if (op.after.revision !== currentRevision(doc)) {
      toast.info("The page moved on since that change — use History to go back further.");
      set({ undoStack: [], redoStack: [] });
      return;
    }
    set({ busy: true });
    try {
      const out = await editorApi.draftApply(projectId, pageId, { baseRevision: doc.revision, source: { view: op.before.view, load: op.before.load } });
      set((s) => ({
        doc: withDraft(doc, out), undoStack: s.undoStack.slice(0, -1), redoStack: [...s.redoStack, op], busy: false,
        saveState: out.dirty ? "unsaved" : "saved", selection: s.selection.filter((id) => out.model.nodes[id]),
      }));
    } catch (err) {
      const f = failureOf(err);
      set({ busy: false, saveState: f.status ? get().saveState : "failed", saveError: f.message });
      toast.error("Couldn't undo.", { description: f.message });
      if (f.code === "stale") await get().reload();
    }
  },

  redo: async () => {
    const { projectId, pageId, doc, redoStack, busy } = get();
    const op = redoStack[redoStack.length - 1];
    if (!projectId || !pageId || !doc || !op || busy) return;
    if (op.before.revision !== currentRevision(doc)) { set({ redoStack: [] }); return; }
    set({ busy: true });
    try {
      const out = await editorApi.draftApply(projectId, pageId, { baseRevision: doc.revision, source: { view: op.after.view, load: op.after.load } });
      set((s) => ({
        doc: withDraft(doc, out), redoStack: s.redoStack.slice(0, -1), undoStack: [...s.undoStack, op], busy: false,
        saveState: out.dirty ? "unsaved" : "saved", selection: s.selection.filter((id) => out.model.nodes[id]),
      }));
    } catch (err) {
      const f = failureOf(err);
      set({ busy: false, saveState: f.status ? get().saveState : "failed", saveError: f.message });
      toast.error("Couldn't redo.", { description: f.message });
    }
  },

  restore: async (revision) => {
    const { projectId, pageId, doc, busy } = get();
    if (!projectId || !pageId || !doc || busy) return;
    set({ busy: true, saveState: "saving" });
    const before = snapshotOf(doc);
    try {
      const out = await editorApi.restore(projectId, pageId, revision, doc.revision);
      const nextDoc = { ...doc, revision: out.revision, model: out.model, source: out.source, history: out.history ? [...doc.history, out.history] : doc.history };
      set((s) => ({
        doc: nextDoc, busy: false, saveState: "saved", showHistory: false,
        undoStack: [...s.undoStack, { label: "Restore version", before, after: snapshotOf(nextDoc) }], redoStack: [],
        selection: s.selection.filter((id) => out.model.nodes[id]),
      }));
      toast.success("Restored that version.");
    } catch (err) {
      const f = failureOf(err);
      set({ busy: false, saveState: "saved" });
      toast.error("Couldn't restore that version.", { description: f.message });
      if (f.code === "stale") await get().reload();
    }
  },

  runCheck: async () => {
    const { projectId, pageId, doc } = get();
    if (!projectId || !pageId || !doc) return;
    set({ checking: true });
    try {
      const out = await editorApi.check(projectId, pageId);
      set({ serverFindings: out.findings, checkedRevision: out.revision, checking: false });
    } catch (err) {
      set({ checking: false });
      toast.error("Couldn't check the page.", { description: failureOf(err).message });
    }
  },

  // ------------------------------------------------------------------ view

  setMode: (mode) => set({ mode, regionSelect: false, editingTextId: null, previewApp: mode === "preview" ? get().previewApp : false }),
  setPreviewApp: (on) => set({ previewApp: on, mode: on ? "preview" : get().mode }),
  setRegionSelect: (on) => set({ regionSelect: on }),
  setViewLevel: (viewLevel) => { set({ viewLevel }); writePrefs(get()); },
  setDevice: (device) => { set({ device }); writePrefs(get()); },
  setCustomWidth: (customWidth) => { set({ customWidth: Math.max(320, Math.min(2560, Math.round(customWidth))), device: "custom" }); writePrefs(get()); },
  setLandscape: (landscape) => set({ landscape }),
  setZoom: (zoom) => { set({ zoom: Math.max(0.25, Math.min(2, zoom)) }); writePrefs(get()); },
  setRouteParam: (name, value) => set((s) => ({ routeParams: { ...s.routeParams, [name]: value } })),
  setLeftTab: (leftTab) => { set({ leftTab, leftOpen: true }); writePrefs(get()); },
  setLeftOpen: (leftOpen) => set({ leftOpen }),
  setRightOpen: (rightOpen) => { set({ rightOpen }); writePrefs(get()); },
  setDrawerTab: (drawerTab) => set({ drawerTab }),
  setShowCode: (showCode) => set({ showCode }),
  setShowHistory: (showHistory) => set({ showHistory }),
  setShowReadiness: (showReadiness) => set({ showReadiness }),
  setEditingTextId: (editingTextId) => set({ editingTextId }),
  setFrame: (patch) => set(patch),

  setSource: (source) => {
    set({ source, frameDoc: null, frameBuildError: null });
    writePrefs(get());
    const { pageId } = get();
    if (source === "jit" && pageId) void get().loadFrame({ pageId, params: {}, search: {} });
  },

  loadFrame: async (target, opts = {}) => {
    const { projectId, pageId, frameTarget } = get();
    const t = target ?? frameTarget ?? (pageId ? { pageId, params: {}, search: {} } : null);
    if (!projectId || !t) return;
    set({ frameTarget: t, frameLoading: true, frameBuildError: null });
    try {
      const bundle: JitBundle = await editorApi.jit(projectId, t.pageId, { params: t.params, search: t.search, fresh: opts.fresh,
                                                                            draft: !!get().doc?.draft && t.pageId === get().pageId });
      // The shared script is fetched once per app and kept as a blob URL; a
      // page built against a newer vendor brings the new one along.
      if (get().vendor?.key !== bundle.vendorKey) {
        const v = await editorApi.vendor(projectId, { fresh: opts.fresh });
        const old = get().vendor;
        if (old && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(old.url);
        const url = typeof URL.createObjectURL === "function" ? URL.createObjectURL(new Blob([v.js], { type: "text/javascript" })) : `vendor:${v.key}`;
        set({ vendor: { key: v.key, url, bytes: v.js.length } });
      }
      // A later request may have superseded this one.
      const now = get().frameTarget;
      if (!now || now.pageId !== t.pageId || JSON.stringify(now.params) !== JSON.stringify(t.params)) return;
      set({ frameDoc: { ...t, js: bundle.js, css: bundle.css, revision: bundle.revision, vendorKey: bundle.vendorKey, ms: bundle.ms, cached: bundle.cached, warnings: bundle.warnings },
            frameLoading: false });
    } catch (err) {
      const f = failureOf(err);
      set({ frameLoading: false, frameBuildError: f.message });
    }
  },

  previewNavigate: (pageId, params, search, replace = false) => {
    const { frameTarget } = get();
    const next = { pageId, params, search };
    set((s) => ({ previewStack: replace || !frameTarget ? s.previewStack : [...s.previewStack, frameTarget].slice(-50) }));
    void get().loadFrame(next);
  },

  previewBack: () => {
    const { previewStack } = get();
    const prev = previewStack[previewStack.length - 1];
    if (!prev) return;
    set({ previewStack: previewStack.slice(0, -1) });
    void get().loadFrame(prev);
  },

  recordAction: (action) => set((s) => ({ actions: [...s.actions, action].slice(-50) })),
  clearActions: () => set({ actions: [] }),

  // ------------------------------------------------------------------ smith

  setSmith: (patch) => set((s) => ({ smith: { ...s.smith, ...patch } })),

  askSmith: async (prompt, annotation = "", prior) => {
    if (get().doc?.draft) {
      // Smith reads the saved page; what is unsaved is saved first.
      const saved = await get().save();
      if (!saved) return;
    }
    const { projectId, pageId, doc, selection, smith } = get();
    if (!projectId || !pageId || !doc || !selection.length || !prompt.trim()) return;
    smith.controller?.abort();
    const controller = new AbortController();
    set({ smith: { ...smith, busy: true, error: null, prompt, annotation, controller, proposalFor: [...selection],
                   proposal: prior ? smith.proposal : null } });
    try {
      const proposal = await editorApi.propose(projectId, pageId, {
        baseRevision: doc.revision, prompt, annotation,
        selection: { type: selection.length > 1 ? "region" : "component", nodeIds: selection },
        breakpoint: get().breakpoint() || "base",
        proposalId: prior ? smith.proposal?.id : undefined,
        prior: prior ?? null,
      }, controller.signal);
      set((s) => ({ smith: { ...s.smith, busy: false, controller: null, proposal, proposalFor: [...selection], log: [...s.smith.log, proposal] } }));
    } catch (err) {
      const f = failureOf(err);
      if (f.code === "cancelled") { set((s) => ({ smith: { ...s.smith, busy: false, controller: null } })); return; }
      set((s) => ({ smith: { ...s.smith, busy: false, controller: null, error: f.message } }));
      if (f.code === "stale") await get().reload();
    }
  },

  cancelSmith: () => {
    const { smith } = get();
    smith.controller?.abort();
    set({ smith: { ...smith, busy: false, controller: null } });
  },

  applyProposal: async (allowScopeExpansion = false) => {
    const { projectId, pageId, doc, smith } = get();
    const proposal = smith.proposal;
    if (!projectId || !pageId || !doc || !proposal || !proposal.valid || get().busy) return;
    if (proposal.baseRevision !== doc.revision) {
      set({ smith: { ...smith, error: "The page changed since this was proposed — ask again." } });
      return;
    }
    set({ busy: true, saveState: "saving" });
    const before = snapshotOf(doc);
    try {
      const out = await editorApi.applyProposal(projectId, pageId, proposal.id, doc.revision, allowScopeExpansion);
      const nextDoc = { ...doc, revision: out.revision, model: out.model, source: out.source, history: out.history ? [...doc.history, out.history] : doc.history };
      set((s) => ({
        doc: nextDoc, busy: false, saveState: "saved",
        undoStack: [...s.undoStack, { label: `Smith: ${proposal.summary}`, before, after: snapshotOf(nextDoc) }], redoStack: [],
        selection: s.selection.filter((id) => out.model.nodes[id]),
        smith: { ...s.smith, proposal: out.proposal, log: s.smith.log.map((p) => (p.id === out.proposal.id ? out.proposal : p)) },
      }));
      toast.success("Applied.", { description: proposal.summary });
    } catch (err) {
      const f = failureOf(err);
      set((s) => ({ busy: false, saveState: "saved", smith: { ...s.smith, error: f.code === "scope" ? null : f.message } }));
      if (f.code === "scope") {
        set((s) => ({ smith: { ...s.smith, proposal: s.smith.proposal ? { ...s.smith.proposal, expandsScope: f.expandsScope ?? s.smith.proposal.expandsScope } : null } }));
      } else if (f.code === "stale") {
        toast.warning("The page changed since Smith proposed this — ask again.");
        await get().reload();
      } else {
        toast.error("Couldn't apply Smith's change.", { description: f.message });
      }
    }
  },

  discardProposal: async () => {
    const { projectId, pageId, smith } = get();
    if (!smith.proposal) return;
    const id = smith.proposal.id;
    set({ smith: { ...smith, proposal: null, proposalFor: [], error: null } });
    if (projectId && pageId && smith.proposal.status !== "applied") {
      try { await editorApi.discardProposal(projectId, pageId, id); } catch { /* already gone */ }
    }
  },

  // ------------------------------------------------------------------ derived

  frameWidth: () => {
    const { device, customWidth, landscape } = get();
    if (device === "custom") return customWidth;
    const d = DEVICE_WIDTHS[device];
    return landscape && device !== "desktop" ? d.h : d.w;
  },
  breakpoint: () => breakpointForWidth(get().frameWidth()),
  labelsFor: (ids) => {
    const { doc } = get();
    const out: Record<string, string> = {};
    for (const id of ids) {
      const node = doc?.model?.nodes[id];
      if (node) out[id] = plainName(node, doc?.registry);
    }
    return out;
  },
}));

/** The revision-aware label for the save state, for the top bar and status bar. */
export function saveLabel(state: SaveState, error: string | null): { text: string; tone: "ok" | "busy" | "bad" } {
  switch (state) {
    case "saving": return { text: "Saving…", tone: "busy" };
    case "checking": return { text: "Checking…", tone: "busy" };
    case "failed": return { text: error ? `Not saved — ${error}` : "Not saved", tone: "bad" };
    case "unsaved": return { text: "Unsaved changes", tone: "busy" };
    default: return { text: "Saved", tone: "ok" };
  }
}

export function historyLabel(entry: HistoryEntry): string {
  return entry.kind === "baseline" ? "Built by Forge" : entry.label;
}

// A saved change is a new revision; the instant canvas rebuilds the open page
// from it (the app-wide preview keeps showing where it went).
useEditorStore.subscribe((s, prev) => {
  if (currentRevision(s.doc) === currentRevision(prev.doc) || !s.doc?.coded || s.source !== "jit" || !s.pageId) return;
  if (s.previewApp && s.frameTarget && s.frameTarget.pageId !== s.pageId) return;
  void s.loadFrame({ pageId: s.pageId, params: s.frameTarget?.params ?? {}, search: s.frameTarget?.search ?? {} });
});
