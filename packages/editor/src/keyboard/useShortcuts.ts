import { useEffect } from "react";
import type { EditorStoreApi } from "../state/store";
import { matches } from "./shortcuts";

export type ShortcutCallbacks = {
  onOpenSwitcher?: () => void;
  onToggleDiff?: () => void;
  onToggleTheme?: () => void;
  onToggleAI?: () => void;
  onToggleHelp?: () => void;
  /** Cmd+Shift+F / Ctrl+Shift+F — open Import from Figma modal. */
  onOpenFigmaImport?: () => void;
};

export function useShortcuts(
  store: EditorStoreApi | null,
  onSave: () => void,
  callbacks?: ShortcutCallbacks
) {
  useEffect(() => {
    if (!store) return;
    const s = store; // narrow to non-null for use inside handler
    function handler(e: KeyboardEvent) {
      // Cmd+Shift+Z (redo) must be checked before Cmd+Z (undo) to avoid partial match
      if (matches(e, { key: "z", meta: true, shift: true })) {
        e.preventDefault();
        s.getState().redo();
        return;
      }
      if (matches(e, { key: "z", meta: true })) {
        e.preventDefault();
        s.getState().undo();
        return;
      }
      if (matches(e, { key: "s", meta: true })) {
        e.preventDefault();
        onSave();
        return;
      }
      if (matches(e, { key: "p", meta: true })) {
        e.preventDefault();
        callbacks?.onOpenSwitcher?.();
        return;
      }
      if (matches(e, { key: "d", meta: true })) {
        e.preventDefault();
        callbacks?.onToggleDiff?.();
        return;
      }
      if (matches(e, { key: "t", meta: true })) {
        e.preventDefault();
        callbacks?.onToggleTheme?.();
        return;
      }
      if (matches(e, { key: "i", meta: true })) {
        e.preventDefault();
        callbacks?.onToggleAI?.();
        return;
      }
      // Linux/Windows fallbacks
      if (matches(e, { key: "z", ctrl: true })) {
        e.preventDefault();
        s.getState().undo();
        return;
      }
      if (matches(e, { key: "y", ctrl: true })) {
        e.preventDefault();
        s.getState().redo();
        return;
      }
      if (matches(e, { key: "p", ctrl: true })) {
        e.preventDefault();
        callbacks?.onOpenSwitcher?.();
        return;
      }
      if (matches(e, { key: "d", ctrl: true })) {
        e.preventDefault();
        callbacks?.onToggleDiff?.();
        return;
      }
      if (matches(e, { key: "t", ctrl: true })) {
        e.preventDefault();
        callbacks?.onToggleTheme?.();
        return;
      }
      if (matches(e, { key: "i", ctrl: true })) {
        e.preventDefault();
        callbacks?.onToggleAI?.();
        return;
      }
      // Cmd+Shift+F / Ctrl+Shift+F — Import from Figma
      if (
        matches(e, { key: "f", meta: true, shift: true }) ||
        matches(e, { key: "f", ctrl: true, shift: true })
      ) {
        e.preventDefault();
        callbacks?.onOpenFigmaImport?.();
        return;
      }
      // Delete / Backspace — bulk delete selected nodes
      if (e.key === "Delete" || e.key === "Backspace") {
        if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
        e.preventDefault();
        s.getState().deleteSelection();
        return;
      }
      // Cmd+C / Ctrl+C — copy selection to clipboard
      if (matches(e, { key: "c", meta: true }) || matches(e, { key: "c", ctrl: true })) {
        if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
        e.preventDefault();
        s.getState().copyToClipboard();
        return;
      }
      // Cmd+X / Ctrl+X — cut selection to clipboard
      if (matches(e, { key: "x", meta: true }) || matches(e, { key: "x", ctrl: true })) {
        if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
        e.preventDefault();
        s.getState().cutToClipboard();
        return;
      }
      // Cmd+V / Ctrl+V — paste from clipboard
      if (matches(e, { key: "v", meta: true }) || matches(e, { key: "v", ctrl: true })) {
        if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
        e.preventDefault();
        s.getState().pasteFromClipboard();
        return;
      }
      // ? — open keyboard help (when not in a text field)
      if (e.key === "?" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault();
        callbacks?.onToggleHelp?.();
        return;
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [store, onSave, callbacks]);
}
