import type { TokenGroups } from "@tentoroforge/library";
import type { ClipboardState, EditorState, PageState, SchemaPath, Suggestion, Viewport } from "./types";

export function selectCurrentPage(s: EditorState): PageState | null {
  if (!s.currentPath) return null;
  return s.pages[s.currentPath] ?? null;
}

export function selectPageState(s: EditorState, path: SchemaPath): PageState | null {
  return s.pages[path] ?? null;
}

export function selectOpenPaths(s: EditorState): SchemaPath[] {
  return Object.values(s.pages)
    .sort((a, b) => a.openedAt - b.openedAt)
    .map((p) => p.schemaPath);
}

export function selectAnyDirty(s: EditorState): boolean {
  return Object.values(s.pages).some((p) => p.saveState === "dirty");
}

export function selectClipboard(s: EditorState): ClipboardState | null {
  return s.clipboard;
}

export function selectTheme(s: EditorState): TokenGroups | null {
  return s.theme;
}

export function selectThemeDirty(s: EditorState): boolean {
  return s.themeDirty;
}

export function selectThemeSource(s: EditorState): "default" | "custom" | null {
  return s.themeSource;
}

export function selectSuggestions(state: EditorState): Suggestion[] {
  const p = selectCurrentPage(state);
  if (!p) return [];
  const dismissed = new Set(p.dismissedIds);
  return p.suggestions.filter((s) => !dismissed.has(s.id));
}

export function selectViewport(state: EditorState): Viewport {
  return state.viewport;
}
