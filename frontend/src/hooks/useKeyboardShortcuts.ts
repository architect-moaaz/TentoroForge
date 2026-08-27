import { useEffect, useCallback } from "react";

interface ShortcutConfig {
  key: string;
  meta?: boolean;
  shift?: boolean;
  ctrl?: boolean;
  action: () => void;
  description: string;
}

/**
 * Hook to register keyboard shortcuts.
 * Uses Cmd on Mac, Ctrl on other platforms.
 */
export function useKeyboardShortcuts(shortcuts: ShortcutConfig[]) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // Don't trigger shortcuts when typing in inputs
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        // Allow Cmd+K even in inputs (command palette)
        const isMeta = e.metaKey || e.ctrlKey;
        if (!(isMeta && e.key.toLowerCase() === "k")) {
          return;
        }
      }

      for (const shortcut of shortcuts) {
        const isMeta = e.metaKey || e.ctrlKey;
        const metaMatch = shortcut.meta ? isMeta : !isMeta;
        const shiftMatch = shortcut.shift ? e.shiftKey : !e.shiftKey;

        if (
          e.key.toLowerCase() === shortcut.key.toLowerCase() &&
          metaMatch &&
          shiftMatch
        ) {
          e.preventDefault();
          shortcut.action();
          return;
        }
      }
    },
    [shortcuts],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);
}

/** Built-in shortcut definitions (for display in command palette) */
export const SHORTCUTS = [
  { key: "K", meta: true, label: "Command Palette" },
  { key: "S", meta: true, label: "Save" },
  { key: "P", meta: true, label: "Toggle Preview" },
  { key: "Z", meta: true, label: "Undo" },
  { key: "1", meta: true, label: "Chat Tab" },
  { key: "2", meta: true, label: "Preview Tab" },
  { key: "3", meta: true, label: "Code Tab" },
] as const;
