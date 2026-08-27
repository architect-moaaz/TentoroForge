/**
 * Undo manager — Spec E Wave 1 runtime primitive.
 *
 * Sits on top of `mutation-queue`: keeps a bounded LIFO stack of
 * inverse mutations, exposes a hook (`useUndoStack`) for UI that
 * wants a "there are 3 undoable actions" badge, and offers
 * `applyLastUndo()` so a global "⌘Z" handler in the shell can invoke
 * the most-recent inverse without walking the DOM.
 *
 * Kept intentionally separate from the mutation-queue itself so a page
 * can wire keyboard-driven undo without importing the full queue's
 * error-toast plumbing.
 */

import * as React from "react";

export interface UndoStackEntry {
  id: string;
  label: string;
  undo: () => void | Promise<void>;
  pushedAt: number;
}

type Listener = (stack: readonly UndoStackEntry[]) => void;

const MAX_STACK = 25;

class UndoStack {
  private entries: UndoStackEntry[] = [];
  private listeners = new Set<Listener>();

  constructor() {
    if (typeof window !== "undefined") {
      window.addEventListener("forge:undo:push", (ev) => {
        const detail = (ev as CustomEvent<UndoStackEntry>).detail;
        if (!detail?.id || typeof detail.undo !== "function") return;
        this.push({ ...detail, pushedAt: Date.now() });
      });
      window.addEventListener("forge:undo:dismiss", (ev) => {
        const { id } = (ev as CustomEvent<{ id: string }>).detail ?? { id: "" };
        this.remove(id);
      });
    }
  }

  subscribe(l: Listener): () => void {
    this.listeners.add(l);
    l(this.entries);
    return () => {
      this.listeners.delete(l);
    };
  }

  private emit() {
    for (const l of this.listeners) l(this.entries);
  }

  push(entry: UndoStackEntry): void {
    // dedupe on id; keep bounded
    this.entries = [...this.entries.filter((e) => e.id !== entry.id), entry].slice(
      -MAX_STACK,
    );
    this.emit();
  }

  remove(id: string): void {
    const before = this.entries.length;
    this.entries = this.entries.filter((e) => e.id !== id);
    if (this.entries.length !== before) this.emit();
  }

  clear(): void {
    if (this.entries.length === 0) return;
    this.entries = [];
    this.emit();
  }

  peek(): UndoStackEntry | undefined {
    return this.entries[this.entries.length - 1];
  }

  async applyLast(): Promise<boolean> {
    const top = this.peek();
    if (!top) return false;
    try {
      await top.undo();
    } finally {
      this.remove(top.id);
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("forge:undo:dismiss", { detail: { id: top.id } }),
        );
      }
    }
    return true;
  }

  snapshot(): readonly UndoStackEntry[] {
    return this.entries;
  }
}

export const undoStack = new UndoStack();

/**
 * React hook — subscribes to the current undo stack.
 */
export function useUndoStack(): readonly UndoStackEntry[] {
  const [s, set] = React.useState<readonly UndoStackEntry[]>(undoStack.snapshot());
  React.useEffect(() => undoStack.subscribe(set), []);
  return s;
}

/**
 * Apply the most-recently-pushed inverse mutation. Suitable target
 * for a shell-level ⌘Z / Ctrl+Z handler.
 */
export function applyLastUndo(): Promise<boolean> {
  return undoStack.applyLast();
}
