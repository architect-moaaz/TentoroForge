/**
 * Design Editor Store — manages GrapeJS editor state.
 *
 * Handles loading/saving annotated HTML, compile status,
 * page selection, and device preview.
 */

import { create } from "zustand";

export type DeviceSize = "desktop" | "tablet" | "mobile";
export type EditorStatus = "idle" | "loading" | "saving" | "compiling" | "error";

interface DesignEditorState {
  /** Project ID */
  projectId: string | null;

  /** Currently selected page */
  activePageId: string | null;

  /** Available pages (loaded from backend) */
  pages: Array<{
    pageId: string;
    route: string;
    title?: string;
    html: string;
    css?: string;
  }>;

  /** Current editor status */
  status: EditorStatus;
  statusMessage: string | null;

  /** Device preview mode */
  devicePreview: DeviceSize;

  /** Whether the editor has unsaved changes */
  isDirty: boolean;

  /** Last compilation result */
  lastCompileResult: {
    files: string[];
    errors: string[];
    warnings: string[];
  } | null;

  /** Project theme CSS (globals.css variables) for canvas injection */
  themeCSS: string;

  // Actions
  setProjectId: (id: string) => void;
  setActivePageId: (pageId: string) => void;
  setPages: (pages: DesignEditorState["pages"]) => void;
  updatePageHtml: (pageId: string, html: string, css?: string) => void;
  setStatus: (status: EditorStatus, message?: string) => void;
  setDevicePreview: (device: DeviceSize) => void;
  setDirty: (dirty: boolean) => void;
  setCompileResult: (result: DesignEditorState["lastCompileResult"]) => void;
  setThemeCSS: (css: string) => void;
  reset: () => void;
}

const initialState = {
  projectId: null,
  activePageId: null,
  pages: [],
  status: "idle" as EditorStatus,
  statusMessage: null,
  devicePreview: "desktop" as DeviceSize,
  isDirty: false,
  lastCompileResult: null,
  themeCSS: "",
};

export const useDesignEditorStore = create<DesignEditorState>((set) => ({
  ...initialState,

  setProjectId: (id) => set({ projectId: id }),

  setActivePageId: (pageId) => set({ activePageId: pageId }),

  setPages: (pages) =>
    set({
      pages,
      activePageId: pages.length > 0 ? pages[0].pageId : null,
    }),

  updatePageHtml: (pageId, html, css) =>
    set((state) => ({
      pages: state.pages.map((p) =>
        p.pageId === pageId ? { ...p, html, css } : p,
      ),
      isDirty: true,
    })),

  setStatus: (status, message) =>
    set({ status, statusMessage: message ?? null }),

  setDevicePreview: (device) => set({ devicePreview: device }),

  setDirty: (dirty) => set({ isDirty: dirty }),

  setCompileResult: (result) => set({ lastCompileResult: result }),

  setThemeCSS: (css) => set({ themeCSS: css }),

  reset: () => set(initialState),
}));
